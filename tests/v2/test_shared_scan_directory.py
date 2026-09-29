"""验证共享接口索引与固定版本缓存；使用SQLite仅替代连接，不替代关系业务逻辑。"""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import sqlite3

from tests.v2.test_mysql_metadata import mysql_compress

import pytest

from opentest.adapters.operation_contract_store import OperationContractStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.application.operation_contracts import OperationContractService
from opentest.application.catalogs import ScanCatalogService
from opentest.application.operation_input_knowledge import OperationInputKnowledgeBuilder
from opentest.application.program_case_analysis import ProgramCaseAnalysisBuilder
from opentest.application.system_relations import SystemRelationService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import (
    DsfOperationDefinition, OperationCapability, OperationKind, OperationMutability,
    ScanManifest, SourceBaseline, SourceReference, ToolDefinition,
    DiscoveredResource, ResourceKind, ResourceRole, SemanticAnalysisResult,
)
from opentest.domain.case_template_v4 import CaseTemplateSourceScope


class _SqlMetadata:
    """执行真实目录SQL；仅去除SQLite不支持的行锁语法，锁并发由真实MySQL测试覆盖。"""

    def __init__(self):
        """建立隔离内存表，并记录查询以检查大对象是否重复传输。"""

        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        # 仅模拟MySQL无损传输和聚合函数，关系选择仍执行生产SQL。
        self.connection.create_function("COMPRESS", 1, mysql_compress)
        self.queries = []
        # 保留业务SQL消费的字段与唯一约束，不在桩中实现任何关系匹配。
        self.connection.executescript("""
        CREATE TABLE ot_system(system_id TEXT PRIMARY KEY,latest_scan_id TEXT,workspace_revision INTEGER DEFAULT 0,is_archived INTEGER DEFAULT 0);
        CREATE TABLE ot_scan(scan_id TEXT PRIMARY KEY,system_id TEXT,source_commit TEXT,selected_revision TEXT,analyzer_version TEXT,completeness TEXT,publication_outcome TEXT,baseline_json TEXT,summary_json TEXT,manifest_gzip BLOB,tools_gzip BLOB,generated_at TEXT);
        CREATE TABLE ot_interface(interface_id INTEGER PRIMARY KEY AUTOINCREMENT,system_id TEXT,scan_id TEXT,operation_id TEXT,kind TEXT,protocol TEXT,route_key TEXT,definition_json TEXT,coverage_json TEXT,latest_contract_revision INTEGER DEFAULT 0,UNIQUE(scan_id,operation_id));
        CREATE TABLE ot_interface_contract_version(interface_id INTEGER,revision INTEGER,contract_json TEXT,PRIMARY KEY(interface_id,revision));
        CREATE TABLE ot_interface_relation(relation_id INTEGER PRIMARY KEY AUTOINCREMENT,source_interface_id INTEGER,target_interface_id INTEGER,consumer_system_id TEXT,provider_system_id TEXT,consumer_scan_id TEXT,provider_scan_id TEXT,callee_operation_id TEXT,protocol TEXT,route_key TEXT,relation_kind TEXT,resolution_status TEXT,evidence_json TEXT);
        """)

    def execute(self, sql, parameters=()):
        """运行生产SQL的占位符等价形式，返回受影响行数。"""

        self.queries.append(sql)
        return self.connection.execute(sql.replace("%s", "?").replace(" FOR UPDATE", "").replace("JSON_ARRAYAGG(", "json_group_array("), parameters).rowcount

    def fetch_all(self, sql, parameters=()):
        """返回驱动形状的字典列表，供生产领域模型校验。"""

        self.queries.append(sql)
        cursor = self.connection.execute(sql.replace("%s", "?").replace(" FOR UPDATE", "").replace("JSON_ARRAYAGG(", "json_group_array("), parameters)
        return [dict(row) for row in cursor.fetchall()]

    def fetch_one(self, sql, parameters=()):
        """查询唯一行；无结果时遵循共享适配器的None契约。"""

        rows = self.fetch_all(sql, parameters)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self):
        """按现有嵌套事务语义提交或回滚本测试数据库。"""

        nested = self.connection.in_transaction
        if not nested:
            self.connection.execute("BEGIN")
        try:
            yield self
            if not nested:
                self.connection.commit()
        except BaseException:
            if not nested:
                self.connection.rollback()
            raise


def test_fixed_interface_cache_avoids_retransfer_and_keeps_resolved_additions_live(tmp_path):
    """静态接口按scan下载一次，随后登记的解析操作仍直接读取共享目录。"""

    metadata = _SqlMetadata()
    metadata.execute("INSERT INTO ot_system(system_id) VALUES(%s)", ("cache-system",))
    operation = OperationCapability(operation_id="facade:demo#run", system_id="cache-system",
        business_name="查询", kind=OperationKind.FACADE, mutability=OperationMutability.READ_ONLY,
        source_scan_id="scan-cache")
    metadata.execute("INSERT INTO ot_interface(system_id,scan_id,operation_id,definition_json) VALUES(%s,%s,%s,%s)",
                     ("cache-system", "scan-cache", operation.operation_id, json.dumps({"operation": operation.model_dump(mode="json")})))
    artifacts = SourceScanArtifactStore(tmp_path, metadata=metadata)
    assert artifacts.read_interface_operations("cache-system", "scan-cache") == [operation]
    before = len(metadata.queries)
    assert artifacts.read_interface_operations("cache-system", "scan-cache") == [operation]
    assert len(metadata.queries) == before
    # 动态resolved_operation不属于缓存字段；写入后仍可立即被后续任务发现。
    contracts = OperationContractStore(tmp_path / "contracts", metadata)
    resolved = DsfOperationDefinition(operation_id="dsf:new.query",
        provider_system_id="provider", gs_name="gs.provider", service_name="detail", action="query", version="1",
        source_refs=[SourceReference(path="Client.java", line=1)])
    contracts.register_operation("cache-system", "scan-cache", resolved)
    assert contracts.read_operations("cache-system", "scan-cache")[resolved.operation_id] == resolved
    assert artifacts.read_interface_operations("cache-system", "scan-cache") == [operation]


class _Store:
    """提供接口投影真正需要的系统身份，不伪造调用图。"""

    def __init__(self, root, metadata):
        """绑定隔离目录和同一个共享数据库。"""

        self.root, self.metadata = root, metadata

    def get_system(self, system_id):
        """读取测试预先注册的系统，缺失不自动创建。"""

        row = self.metadata.fetch_one("SELECT system_id FROM ot_system WHERE system_id=%s", (system_id,))
        if row is None:
            raise KnowledgeValidationError("system missing")
        return SimpleNamespace(system_id=system_id)

    def list_systems(self):
        """读取已注册系统，供远端目录启动预热验证。"""

        return [SimpleNamespace(system_id=row["system_id"]) for row in self.metadata.fetch_all("SELECT system_id FROM ot_system")]

    def source_scan_matches_configured_version(self, system_id, baseline):
        """本夹具没有源码pin，已注册系统的保存基线可用于首次选择。"""

        return self.get_system(system_id) is not None


def _remote(provider="bbb", symbol="sample.Api#query"):
    """构造固定发布坐标，符号变化用于验证不能按路由或方法名误配。"""

    return DsfOperationDefinition(operation_id="dsf:bbb:api:query", provider_system_id=provider,
        gs_name="group-bbb", service_name="api", version="1", action="query",
        source_refs=[SourceReference(path="Api.java", symbol=symbol, line=1)],
        request_schema={"type": "object", "properties": {}}, response_schema={"type": "object", "properties": {}})


def _scan(system, scan, declarations, tmp_path):
    """返回带固定commit与DSF声明的扫描，测试不需要真正执行业务。"""

    return ScanManifest(system_id=system, scan_id=scan, baseline=SourceBaseline(source_path=str(tmp_path), commit="a" * 40), dsf_operations=declarations)


def _publish(service, manifest, operations=()):
    """沿生产准备和发布顺序写入接口索引，关系算法保持原实现。"""

    # 发布关系的扫描身份也必须存在于共享历史，页面会校验当前指针是否有效。
    if service.artifacts.metadata.fetch_one("SELECT scan_id FROM ot_scan WHERE scan_id=%s", (manifest.scan_id,)) is None:
        service.artifacts.metadata.execute("INSERT INTO ot_scan(scan_id,system_id) VALUES(%s,%s)", (manifest.scan_id, manifest.system_id))
    catalog = ProgramCaseAnalysisBuilder().build(manifest)
    service.prepare_interfaces(manifest, list(operations), catalog)
    with service.artifacts.metadata.transaction():
        service.reconcile_published_scan(manifest.system_id, manifest.scan_id)
        service.artifacts.metadata.execute("UPDATE ot_system SET latest_scan_id=%s WHERE system_id=%s", (manifest.scan_id, manifest.system_id))


def test_registration_completes_reverse_relations_and_removes_old_routes(tmp_path):
    """先A后B自动闭合双方索引，B删除旧路由后A旧引用回到未知，不残留假关系。"""

    database = _SqlMetadata()
    for system in ("aaa", "bbb"):
        database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (system,))
    artifacts = SourceScanArtifactStore(tmp_path, database)
    service = SystemRelationService(_Store(tmp_path, database), artifacts)
    # A未证明所属入口时保留声明关系，不伪造执行调用者。
    _publish(service, _scan("aaa", "scan-aaa-1", [_remote()], tmp_path))
    assert service.catalog("aaa").interface_relations[0].resolution_status == "unresolved"
    _publish(service, _scan("bbb", "scan-bbb-1", [_remote()], tmp_path))
    forward = service.catalog("aaa").interface_relations[0]
    assert (forward.target_system_id, forward.target_scan_id) == ("bbb", "scan-bbb-1")
    assert forward.source_operation_id == ""
    assert service.catalog("bbb").upstream[0].system_id == "aaa"
    _publish(service, _scan("bbb", "scan-bbb-2", [], tmp_path))
    assert service.catalog("aaa").interface_relations[0].resolution_status == "unresolved"
    assert not service.catalog("bbb").upstream
    assert not any("manifest_gzip" in query for query in database.queries)


def test_provider_ambiguity_is_reconciled_when_one_publication_disappears(tmp_path):
    """提供方增加与移除都会重算相同旧坐标，解除歧义不能依赖旧target ID。"""

    database = _SqlMetadata()
    for system in ("aaa", "bbb", "ccc"):
        database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (system,))
    service = SystemRelationService(_Store(tmp_path, database), SourceScanArtifactStore(tmp_path, database))
    # 两个系统发布完全相同坐标/符号时明确歧义，不能选列表第一项。
    _publish(service, _scan("aaa", "scan-aaa", [_remote()], tmp_path))
    _publish(service, _scan("bbb", "scan-bbb", [_remote()], tmp_path))
    _publish(service, _scan("ccc", "scan-ccc", [_remote("ccc")], tmp_path))
    assert service.catalog("aaa").interface_relations[0].resolution_status == "ambiguous"
    _publish(service, _scan("ccc", "scan-ccc-new", [], tmp_path))
    assert service.catalog("aaa").interface_relations[0].target_system_id == "bbb"


def test_remote_history_and_workspace_revision_do_not_require_scan_download(tmp_path):
    """第二工作台直接读取历史小摘要和共享revision，启动预热不下载未使用扫描。"""

    database = _SqlMetadata()
    database.execute("INSERT INTO ot_system(system_id) VALUES('aaa')")
    first = SourceScanArtifactStore(tmp_path / "first", database)
    manifest = _scan("aaa", "scan-history", [], tmp_path)
    first.write_manifest(manifest)
    first.publish_latest("aaa", manifest.scan_id)
    assert first.workspace_revisions.read("aaa") == 1
    second = SourceScanArtifactStore(tmp_path / "second", database)
    catalogs = ScanCatalogService(_Store(tmp_path, database), second)
    database.queries.clear()
    assert catalogs.prewarm_latest() == {"warmed": 0, "skipped": 1}
    history = catalogs.list_history("aaa")
    assert history[0].latest is True
    assert history[0].counts == {"facade": 0, "job": 0, "mq_consumer": 0, "state_machine": 0, "state_transition": 0}
    # 他机知识修改推进共享版本后，当前目录不能继续使用本地版本判断缓存命中。
    first.workspace_revisions.bump("aaa")
    assert second.workspace_revisions.read("aaa") == 2
    assert not any("manifest_gzip" in query for query in database.queries)
    assert not second.scan_root.exists()


def test_dependency_selection_follows_frozen_anchors_beyond_two_hops(tmp_path):
    """A选B后可按需求继续C、D，B/C新latest不能替换已经固定的来源scan。"""

    database = _SqlMetadata()
    service = SystemRelationService(_Store(tmp_path, database), SourceScanArtifactStore(tmp_path, database))
    declarations = {}
    operations = {}
    manifests = {}
    for system in ("aaa", "bbb", "ccc", "ddd"):
        database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (system,))
        declarations[system] = _remote(system, f"sample.{system}.Api#query").model_copy(update={
            "operation_id": f"dsf:{system}:api:query", "gs_name": f"group-{system}"})
        operations[system] = OperationCapability(operation_id=f"facade:sample.{system}.Api#query", system_id=system,
            business_name="查询", kind=OperationKind.FACADE, mutability=OperationMutability.READ_ONLY,
            source_scan_id=f"scan-{system}-1", provider_operation_id=declarations[system].operation_id, executable=True)
    for index, system in enumerate(("aaa", "bbb", "ccc", "ddd")):
        remotes = [declarations[system]]
        capabilities = [operations[system]]
        if index < 3:
            downstream = ("bbb", "ccc", "ddd")[index]
            remotes.append(declarations[downstream])
            capabilities.append(OperationCapability(operation_id=declarations[downstream].operation_id,
                system_id=system, business_name="外部查询", kind=OperationKind.EXTERNAL_DSF,
                mutability=OperationMutability.READ_ONLY, source_scan_id=f"scan-{system}-1",
                provider_definition=declarations[downstream], executable=True))
        manifest = _scan(system, f"scan-{system}-1", remotes, tmp_path)
        manifests[system] = manifest
        service.artifacts.write_manifest(manifest)
        _publish(service, manifest, capabilities)
    scopes = [CaseTemplateSourceScope(source_system_id="aaa", source_scan_id="scan-aaa-1", source_baseline=manifests["aaa"].baseline)]
    for system in ("bbb", "ccc", "ddd"):
        selected = service.resolve_from_scopes(scopes, declarations[system].operation_id)
        assert (selected.system_id, selected.operation_id, selected.source_scan_id) == (system, operations[system].operation_id, f"scan-{system}-1")
        scopes.append(CaseTemplateSourceScope(source_system_id=system, source_scan_id=selected.source_scan_id,
            source_baseline=manifests[system].baseline, selected_operation_ids=[selected.operation_id]))
    # 新B移除C引用、新C发布同名方法，仍从已固定B1声明匹配已固定C1。
    for system in ("bbb", "ccc"):
        newer = _scan(system, f"scan-{system}-2", [declarations[system]], tmp_path)
        service.artifacts.write_manifest(newer)
        _publish(service, newer, [operations[system].model_copy(update={"source_scan_id": newer.scan_id})])
    selected = service.resolve_from_scopes(scopes[:3], declarations["ccc"].operation_id)
    assert selected.source_scan_id == "scan-ccc-1"
    assert selected.system_id == "ccc"


def test_basic_contract_is_persisted_and_read_without_derivation(tmp_path):
    """扫描基础契约直接远程读取，字段未知与optional区分，修订只能追加。"""

    database = _SqlMetadata()
    database.execute("INSERT INTO ot_system(system_id,latest_scan_id) VALUES('aaa','scan-aaa')")
    artifacts = SourceScanArtifactStore(tmp_path, database)
    manifest = _scan("aaa", "scan-aaa", [], tmp_path)
    artifacts.write_manifest(manifest)
    operation = OperationCapability(operation_id="dsf:aaa:query", system_id="aaa", business_name="查询", kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY, source_scan_id=manifest.scan_id,
        publication_input_schema={"type": "object", "properties": {}})
    relations = SystemRelationService(_Store(tmp_path, database), artifacts)
    relations.prepare_interfaces(manifest, [operation], ProgramCaseAnalysisBuilder().build(manifest))
    base = OperationInputKnowledgeBuilder().build(operation, None, manifest.scan_id).model_copy(update={"source_commit": manifest.baseline.commit})
    store = OperationContractStore(tmp_path / "contracts", database)
    store.save("aaa", base)
    service = OperationContractService(_Store(tmp_path, database), artifacts, None)
    database.queries.clear()
    assert service.get_contract("aaa", operation.operation_id) == base
    assert not any("manifest_gzip" in query for query in database.queries)
    store.save("aaa", base.model_copy(update={"contract_revision": 1, "operation_summary": "补充"}))
    assert store.get_revision("aaa", manifest.scan_id, operation.operation_id, 0) == base
    # 中断后的相同扫描重放不能抹去补充版本或后来登记的精确外部定义。
    resolved = _remote().model_copy(update={"operation_id": operation.operation_id})
    store.register_operation("aaa", manifest.scan_id, resolved)
    relations.prepare_interfaces(manifest, [operation], ProgramCaseAnalysisBuilder().build(manifest))
    assert store.get_latest("aaa", manifest.scan_id, operation.operation_id).contract_revision == 1
    assert store.read_operations("aaa", manifest.scan_id)[operation.operation_id] == resolved
    with pytest.raises(KnowledgeValidationError, match="原始事实发生冲突"):
        relations.prepare_interfaces(manifest, [operation.model_copy(update={"business_name": "被改写"})], ProgramCaseAnalysisBuilder().build(manifest))
    with pytest.raises(KnowledgeValidationError, match="覆盖历史"):
        store.save("aaa", base.model_copy(update={"contract_revision": 1}))


def test_second_workspace_downloads_each_immutable_artifact_only_once(tmp_path):
    """不同目录工作台按scan缓存，工具只在执行需要时下载并还原相对路径。"""

    database = _SqlMetadata()
    database.execute("INSERT INTO ot_system(system_id,latest_scan_id) VALUES('aaa','scan-cache')")
    first = SourceScanArtifactStore(tmp_path / "first", database)
    tool_root = first.tool_root / "aaa" / "scan-cache"
    tool_root.mkdir(parents=True)
    (tool_root / "run.py").write_text("print('same-version')\n")
    manifest = _scan("aaa", "scan-cache", [], tmp_path / "source-one").model_copy(update={"tool_root": str(tool_root)})
    first.write_manifest(manifest)
    second = SourceScanArtifactStore(tmp_path / "second", database)
    second.source_path_resolver = lambda _: str(tmp_path / "source-two")
    database.queries.clear()
    read = second.read("aaa")
    assert read.baseline.source_path == str(tmp_path / "source-two")
    assert read.tool_root == str(second.tool_root / "aaa" / "scan-cache")
    assert not Path(read.tool_root).exists()
    second.read("aaa")
    root = second.ensure_tool_bundle("aaa", "scan-cache")
    second.ensure_tool_bundle("aaa", "scan-cache")
    assert (root / "run.py").read_text() == "print('same-version')\n"
    assert sum("SELECT manifest_gzip" in query for query in database.queries) == 1
    assert sum("SELECT tools_gzip" in query for query in database.queries) == 1


def test_mq_publication_matches_multiple_consumers_without_dsf_ambiguity():
    """MQ同topic多消费者合法，匹配各自tag，不能套用RPC唯一provider规则。"""

    reference = {"protocol": "MQ", "tags": ["CREATED"]}
    assert SystemRelationService._matches_publication(reference, {"mq_publication": {"tags": ["*"]}})
    assert SystemRelationService._matches_publication(reference, {"mq_publication": {"tags": ["CREATED"]}})
    assert not SystemRelationService._matches_publication(reference, {"mq_publication": {"tags": ["DELETED"]}})


def test_mq_sender_requires_exact_callsite_to_associate_entry(tmp_path):
    """MQ发送必须按行定位调用方法，类名相同但调用点不明时保留声明级未知。"""

    manifest = _scan("aaa", "scan-mq", [], tmp_path)
    reference = SourceReference(path="Order.java", symbol="Order", line=12)
    manifest.resources = [DiscoveredResource(resource_id="mq:order", system_id="aaa", kind=ResourceKind.MQ,
        role=ResourceRole.PRODUCER, logical_name="order", source_refs=[reference])]
    symbol = "sample.Order#create()"
    operation = OperationCapability(operation_id="facade:Order#create", system_id="aaa", business_name="创建订单",
        kind=OperationKind.FACADE, mutability=OperationMutability.WRITE, source_scan_id=manifest.scan_id,
        source_symbol_refs=[SourceReference(path="Order.java", symbol=symbol, line=10)])
    manifest.semantic_analysis = SemanticAnalysisResult.model_validate({"system_id": "aaa", "methods": [{
        "symbol_id": symbol, "qualified_class_name": "sample.Order", "method_name": "create",
        "source_ref": {"path": "Order.java", "symbol": symbol, "line": 10}}], "call_edges": [{
        "caller_symbol_id": symbol, "callee_expression": "publisher.send", "resolution_status": "unresolved",
        "source_ref": {"path": "Order.java", "symbol": symbol, "line": 12}}]})
    service = SystemRelationService(None, SourceScanArtifactStore(tmp_path))
    service._mq_source_root = Mock(return_value=tmp_path)
    service._mq_endpoint = Mock(return_value=SimpleNamespace(cluster={"test-cluster"}, topic="order", tags={"CREATED"}))
    definitions = service._interface_definitions(manifest, [operation])
    assert definitions[operation.operation_id]["references"][0]["kind"] == "MESSAGE"
    # 方法体里的其他位置不是发送证据；不能靠同类名猜测调用入口。
    manifest.resources[0].source_refs[0].line = 30
    unknown = service._interface_definitions(manifest, [operation])
    assert unknown[operation.operation_id]["references"] == []
    assert unknown["mq:mq:order"]["references"][0]["kind"] == "DECLARATION"
    # 历史源码无法匹配时，不允许使用当前checkout配置闭合历史消息关系。
    service._mq_source_root.side_effect = KnowledgeValidationError("source drift")
    service._mq_endpoint.reset_mock()
    unavailable = service._interface_definitions(manifest, [operation])
    assert unavailable["mq:mq:order"]["relation_gap"] == "MQ_SOURCE_UNAVAILABLE"
    service._mq_endpoint.assert_not_called()


def test_cross_version_discovery_is_bidirectional_but_not_execution_scope(tmp_path):
    """版本不同仍展示双向依赖，严格执行范围不借此接入提供方；更新与歧义可重算。"""

    database = _SqlMetadata()
    for system in ("aaa", "bbb", "ccc"):
        database.execute("INSERT INTO ot_system(system_id) VALUES(%s)", (system,))
    service = SystemRelationService(_Store(tmp_path, database), SourceScanArtifactStore(tmp_path, database))
    # 先接入引用旧版本的调用方，再接入唯一新版本提供方，覆盖本次真实漏匹配情形。
    _publish(service, _scan("aaa", "scan-aaa-old", [_remote()], tmp_path))
    newer = _remote().model_copy(update={"version": "2"})
    _publish(service, _scan("bbb", "scan-bbb-new", [newer], tmp_path))
    forward = service.discovery_catalog("aaa")
    assert forward.downstream[0].system_id == "bbb"
    edge = forward.interface_relations[0]
    assert (edge.resolution_status, edge.source_version, edge.target_version) == ("version_mismatch", "1", "2")
    assert service.discovery_catalog("bbb").upstream[0].system_id == "aaa"
    assert service.system_ids("aaa") == ["aaa"]
    # 第二提供方有同一接口时不能凭系统名称猜测；删除后自动恢复唯一跨版本关系。
    duplicate = newer.model_copy(update={"provider_system_id": "ccc"})
    _publish(service, _scan("ccc", "scan-ccc-1", [duplicate], tmp_path))
    assert service.catalog("aaa").interface_relations[0].resolution_status == "ambiguous"
    assert not service.discovery_catalog("aaa").downstream
    _publish(service, _scan("ccc", "scan-ccc-2", [], tmp_path))
    assert service.discovery_catalog("bbb").upstream[0].system_id == "aaa"
    _publish(service, _scan("bbb", "scan-bbb-removed", [], tmp_path))
    assert not service.discovery_catalog("aaa").downstream
