"""共享发布的员工隔离、CAS、固定范围和单项投影业务验收。"""

from __future__ import annotations

import json
import re
import sqlite3
import zlib
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock

import pytest

from opentest.adapters.mysql_metadata import MySqlMetadataStore, hydrate_scope_record, portable_scope_payload
from opentest.application.publication import PublicationService, contract_test_content, equivalent_knowledge
from opentest.domain.case_template_v4 import CaseTemplateGenerationV4
from opentest.domain.errors import IdempotencyConflictError, KnowledgeNotFoundError, KnowledgeValidationError, MetadataConnectionError, ScopeViolationError
from opentest.domain.models import KnowledgeNode
from opentest.domain.publication import CaseDraftUpdate, DraftResolution, InterfaceDraftUpdate, PublicationRequest, PublicationScope
from opentest.domain.shared_workspace import InterfaceKnowledgeBundle


def mysql_compress(payload):
    """为离线SQLite夹具实现MySQL COMPRESS的传输格式；NULL保持为空，不改变业务JSON。"""

    if payload is None:
        return None
    # 生产解码器要求四字节原长度及zlib正文，测试不能绕过实际压缩解析路径。
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    return len(raw).to_bytes(4, "little") + zlib.compress(raw)


class PublicationDatabase:
    """使用真实SQL事务验证业务写入；仅转换SQLite与MySQL的占位符和时间语法。"""

    workspace_id = "test-workspace"

    def __init__(self):
        """建立独立内存数据库及发布所需表，测试结束由进程释放。"""

        # 测试适配器保留真实存储与事务行为，不能由业务Mock代替可见性及CAS判定。
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("COMPRESS", 1, mysql_compress)
        self.lock = RLock()
        self.connection.executescript("""
        CREATE TABLE ot_system(system_id TEXT PRIMARY KEY,workspace_revision INTEGER DEFAULT 0);
        CREATE TABLE ot_code_baseline(baseline_id TEXT PRIMARY KEY,system_id TEXT,source_kind TEXT DEFAULT 'LEGACY',
          source_commit TEXT,selected_revision TEXT DEFAULT '',source_artifact_id TEXT,created_by_user_id TEXT,
          context_json TEXT,interview_json TEXT,questions_json TEXT,inherited_from_baseline_id TEXT,
          context_revision INTEGER DEFAULT 0,updated_by_user_id TEXT,
          created_at TEXT DEFAULT '2026-10-22T00:00:00Z',updated_at TEXT DEFAULT '2026-10-22T00:00:00Z');
        CREATE TABLE ot_scan(scan_id TEXT PRIMARY KEY,baseline_id TEXT,created_by_user_id TEXT,system_id TEXT DEFAULT 'orders');
        CREATE TABLE ot_interface(interface_id INTEGER PRIMARY KEY,system_id TEXT,scan_id TEXT,operation_id TEXT);
        CREATE TABLE ot_interface_contract_version(interface_id INTEGER,revision INTEGER,contract_json TEXT,knowledge_json TEXT,author_user_id TEXT);
        CREATE TABLE ot_baseline_interface(baseline_interface_id INTEGER PRIMARY KEY,baseline_id TEXT,operation_id TEXT,current_interface_id INTEGER,
          current_contract_revision INTEGER,publication_revision INTEGER DEFAULT 0,availability TEXT,published_by_user_id TEXT,published_at TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE ot_interface_draft(baseline_interface_id INTEGER,owner_user_id TEXT,interface_id INTEGER,contract_revision INTEGER,
          change_kind TEXT,expected_publication_revision INTEGER,draft_revision INTEGER,status TEXT,updated_at TEXT,
          PRIMARY KEY(baseline_interface_id,owner_user_id));
        CREATE TABLE ot_case(case_id TEXT PRIMARY KEY,baseline_interface_id INTEGER,current_generation_id TEXT,current_variant_id TEXT,
          publication_revision INTEGER DEFAULT 0,knowledge_dependencies_json TEXT,impact_status TEXT,impact_details_json TEXT,
          published_by_user_id TEXT,published_at TEXT,updated_at TEXT,created_by_user_id TEXT,created_at TEXT);
        CREATE TABLE ot_case_draft(case_id TEXT,owner_user_id TEXT,generation_id TEXT,variant_id TEXT,expected_publication_revision INTEGER,
          draft_revision INTEGER,status TEXT,updated_at TEXT,PRIMARY KEY(case_id,owner_user_id));
        CREATE TABLE ot_case_generation(generation_id TEXT PRIMARY KEY,system_id TEXT,baseline_id TEXT,owner_user_id TEXT,generation_json TEXT);
        CREATE TABLE ot_execution(execution_id TEXT PRIMARY KEY,execution_kind TEXT,system_id TEXT,baseline_id TEXT,
          generation_id TEXT,environment_id TEXT,payload_json TEXT,created_at TEXT);
        CREATE TABLE ot_workflow_record(record_kind TEXT,record_id TEXT,system_id TEXT,baseline_id TEXT,owner_user_id TEXT,status TEXT,
          revision INTEGER,owner_workspace_id TEXT,payload_json TEXT,created_at TEXT,updated_at TEXT,PRIMARY KEY(record_kind,record_id));
        """)

    def _sql(self, sql: str) -> str:
        """转换驱动语法而不改变业务谓词；返回可由SQLite执行的同一查询。"""

        sql = sql.replace("%s", "?").replace("CURRENT_TIMESTAMP(6)", "CURRENT_TIMESTAMP").replace(" FOR UPDATE", "").replace("INSERT IGNORE", "INSERT OR IGNORE")
        # SQLite冲突更新语法不同，但仍由真实唯一键和事务判断同一Case草稿的覆盖。
        if " ON DUPLICATE KEY UPDATE " in sql:
            insert, update = sql.split(" ON DUPLICATE KEY UPDATE ", 1)
            update = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", update)
            return insert + " ON CONFLICT DO UPDATE SET " + update
        return sql

    def fetch_one(self, sql: str, parameters=()):
        """执行一行查询，返回与MySQL字典游标相同的结果或None。"""

        row = self.connection.execute(self._sql(sql), parameters).fetchone()
        return dict(row) if row is not None else None

    def fetch_all(self, sql: str, parameters=()):
        """完整取回查询结果以验证列表范围；不使用测试端过滤补救SQL。"""

        return [dict(row) for row in self.connection.execute(self._sql(sql), parameters).fetchall()]

    def execute(self, sql: str, parameters=()):
        """执行实际参数化写入并返回受影响行数，数据库错误照常传播。"""

        return self.connection.execute(self._sql(sql), parameters).rowcount

    def read_execution(self, kind, execution_id):
        """读取实际执行表记录，供单Case投影验证历史选择和环境过滤。"""

        row = self.fetch_one("SELECT payload_json FROM ot_execution WHERE execution_id=%s AND execution_kind=%s", (execution_id, kind))
        return json.loads(row["payload_json"]) if row else None

    @contextmanager
    def transaction(self):
        """串行持有本测试数据库事务，异常回滚；业务仍按每项提交验收。"""

        with self.lock:
            # 同系统工作流可以嵌套调用草稿服务，复用外层事务以保持版本和草稿原子提交。
            if self.connection.in_transaction:
                yield
                return
            self.connection.execute("BEGIN")
            try:
                yield
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise


class KnowledgeTransactions:
    """提供现有知识存储事务协议，不模拟发布业务或可见性判断。"""

    def __init__(self, metadata):
        """绑定实际测试SQL存储并记录系统锁范围。"""

        # 测试适配器保留真实存储与事务行为，不能由业务Mock代替可见性及CAS判定。
        self.metadata = metadata
        self.workspace_revisions = self
        self.locked = []

    def system_transaction(self, system_id):
        """使用实际数据库事务保护一个系统，返回上下文管理器。"""

        self.locked.append({system_id})
        return self.metadata.transaction()

    def multi_system_transaction(self, system_ids):
        """记录业务选择的实际多系统范围并返回实际事务。"""

        self.locked.append(set(system_ids))
        return self.metadata.transaction()

    def bump(self, system_id):
        """随业务事务推进实际数据库缓存版本，失败会共同回滚。"""

        self.metadata.execute("UPDATE ot_system SET workspace_revision=workspace_revision+1 WHERE system_id=%s", (system_id,))


def contract_payload(summary="订单查询"):
    """构造首个入口的固定独立契约；summary可模拟真实业务用途变化。"""

    return {"contract_version": "operation-contract/v2", "contract_revision": 1, "target_id": "query-1",
            "source_scan_id": "scan-1", "status": "READY", "request_schema": {"type": "object", "properties": {}},
            "fields": [], "response_schema": {}, "operation_summary": summary}


def seed_interface(database, identity, owner="employee-a", summary="订单查询"):
    """插入与入口/扫描身份一致的独立契约及可选正文，模拟扫描完成但尚未共享。"""

    # 固定知识与本人草稿分开插入，验证发布前共享指针始终为空。
    node = KnowledgeNode(node_id="node-order", system_id="orders", kind="facade", title="订单查询")
    bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={"node-order": summary})
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id) VALUES(%s,%s)", (f"scan-{identity}", "baseline-one"))
    database.execute("INSERT INTO ot_interface VALUES(%s,%s,%s,%s)", (identity, "orders", f"scan-{identity}", f"query-{identity}"))
    contract = {**contract_payload(summary), "target_id": f"query-{identity}", "source_scan_id": f"scan-{identity}"}
    database.execute("INSERT INTO ot_interface_contract_version VALUES(%s,1,%s,%s,%s)",
                     (identity, json.dumps(contract), bundle.model_dump_json(), owner))
    database.execute("INSERT INTO ot_baseline_interface(baseline_interface_id,baseline_id,operation_id,availability) VALUES(%s,%s,%s,'UNPUBLISHED')",
                     (identity, "baseline-one", f"query-{identity}"))
    database.execute("INSERT INTO ot_interface_draft VALUES(%s,%s,%s,1,'UPSERT',0,1,'READY',NULL)", (identity, owner, identity))


@pytest.fixture
def publication():
    """提供独立服务和数据库；所有数据仅存在本测试进程，不连接真实MySQL。"""

    # 事务和过滤由真实SQL执行，fixture不预先裁剪其他员工的数据。
    database = PublicationDatabase()
    database.execute("INSERT INTO ot_system(system_id) VALUES('orders')")
    database.execute("INSERT INTO ot_code_baseline(baseline_id,system_id) VALUES('baseline-one','orders')")
    service = PublicationService(KnowledgeTransactions(database))
    scope = PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-a")
    yield service, database, scope
    database.connection.close()


def test_all_publication_freezes_scope_and_excludes_other_employee(publication):
    """all覆盖所有本人员工草稿；同请求重发不得夹带后来生成或其他人的草稿。"""

    # 同一发布点击前后加入不同员工与后生成草稿，覆盖分页和网络重试最容易越界的边界。
    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2, "employee-b")
    request = PublicationRequest(request_id="request-all-0001", scope="all")
    first = service.publish(scope, "interfaces", request)
    seed_interface(database, 3)
    repeated = service.publish(scope, "interfaces", request)
    assert first == repeated
    assert [result.item_id for result in repeated.results] == ["1"]
    assert [item["baseline_interface_id"] for item in service.list_interfaces(scope)] == [1]
    assert [item["baseline_interface_id"] for item in service.list_interfaces(scope, "mine")] == [3]
    other = scope.model_copy(update={"user_id": "employee-b"})
    assert [item["baseline_interface_id"] for item in service.list_interfaces(other, "mine")] == [2]
    with pytest.raises(IdempotencyConflictError):
        service.publish(other, "interfaces", request)


def test_conflict_requires_explicit_seen_revision_and_then_can_publish(publication):
    """另一员工发布后旧草稿保留，明确查看新版本并保留修改后才能再次发布。"""

    # 两人并发起点相同；第二人必须基于重新看到的版本显式解决冲突。
    service, database, scope = publication
    seed_interface(database, 1)
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-initial", scope="all"))
    database.execute("INSERT INTO ot_interface_contract_version VALUES(1,2,%s,%s,'employee-b')",
                     (json.dumps(contract_payload("新约束")), database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version LIMIT 1")["knowledge_json"]))
    database.execute("INSERT INTO ot_interface_draft VALUES(1,'employee-b',1,2,'UPSERT',0,1,'READY',NULL)")
    other = scope.model_copy(update={"user_id": "employee-b"})
    conflict = service.publish(other, "interfaces", PublicationRequest(request_id="request-conflict", scope="all"))
    assert conflict.results[0].status == "CONFLICT"
    with pytest.raises(IdempotencyConflictError):
        service.resolve_draft(other, "interfaces", DraftResolution(item_id="1", draft_revision=1, publication_revision=0))
    service.resolve_draft(other, "interfaces", DraftResolution(item_id="1", draft_revision=1, publication_revision=1))
    completed = service.publish(other, "interfaces", PublicationRequest(request_id="request-resolved", scope="all"))
    assert completed.results[0].status == "PUBLISHED"
    assert completed.results[0].publication_revision == 2


def test_old_task_cannot_publish_edited_draft(publication):
    """发布范围冻结后个人草稿变化时返回冲突，不把新草稿误认为先前点击的内容。"""

    # 模拟发布集合已冻结后本人又编辑，旧点击不得覆盖更新内容。
    service, database, scope = publication
    seed_interface(database, 1)
    request = PublicationRequest(request_id="request-edited-1", scope="all")
    service._freeze_request(scope, "interfaces", request)
    database.execute("UPDATE ot_interface_draft SET draft_revision=2 WHERE baseline_interface_id=1")
    result = service.publish(scope, "interfaces", request)
    assert result.results[0].reason_code == "DRAFT_CHANGED"
    assert service.list_interfaces(scope) == []


def test_missing_contract_blocks_publication_without_closing_draft(publication):
    """没有固定独立契约仍不能发布，失败项不撤销其他成功结果。"""

    # 合法接口与缺材料接口同时发布，要求逐项成功而非全批吞错。
    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2)
    database.execute("UPDATE ot_interface_contract_version SET contract_json=NULL WHERE interface_id=2")
    result = service.publish(scope, "interfaces", PublicationRequest(request_id="request-partial1", scope="all"))
    assert [item.status for item in result.results] == ["PUBLISHED", "BLOCKED"]
    assert [item["baseline_interface_id"] for item in service.list_interfaces(scope, "mine")] == [2]


@pytest.mark.parametrize("corruption", ["scope", "model", "json", "missing"])
def test_invalid_case_asset_is_recorded_without_blocking_other_items(publication, corruption):
    """坏Case产物在依赖范围探测时也须逐项阻断，不泄漏原文；有效同批项仍发布且回执可重放。"""

    service, database, scope = publication
    seed_interface(database, 1)
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-case-prerequisite", scope="all"))
    for case_id, digit in (("case-bad", "a"), ("case-good", "b")):
        payload = generation_payload()
        payload["generation_id"] = "case-template-generation-" + digit * 20
        payload["case_bindings"][0]["case_id"] = case_id
        serialized = json.dumps(payload)
        baseline_id = "baseline-one"
        # 故障落在真实存储数据中，依赖发现必须经过生产投影与严格模型。
        if case_id == "case-bad":
            if corruption == "scope":
                baseline_id = "baseline-other"
            elif corruption == "model":
                payload["status"] = "PRIVATE-INVALID-STATUS"
                serialized = json.dumps(payload)
            elif corruption == "json":
                serialized = "PRIVATE-BROKEN-JSON"
        if case_id != "case-bad" or corruption != "missing":
            database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders',%s,'employee-a',%s)",
                (payload["generation_id"], baseline_id, serialized))
        database.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES(%s,1)", (case_id,))
        database.execute("INSERT INTO ot_case_draft VALUES(%s,'employee-a',%s,%s,0,1,'READY',NULL)",
            (case_id, payload["generation_id"], payload["variants"][0]["variant_id"]))

    request = PublicationRequest(request_id=f"request-invalid-{corruption}", scope="all")
    receipt = service.publish(scope, "cases", request)
    assert receipt.status == "COMPLETED"
    assert [(item.item_id, item.status) for item in receipt.results] == [("case-bad", "BLOCKED"), ("case-good", "PUBLISHED")]
    assert "PRIVATE" not in receipt.model_dump_json()
    assert service.publish(scope, "cases", request) == receipt
    assert database.fetch_one("SELECT current_generation_id FROM ot_case WHERE case_id='case-bad'")["current_generation_id"] is None
    assert database.fetch_one("SELECT status FROM ot_case_draft WHERE case_id='case-bad'")["status"] == "READY"
    assert database.fetch_one("SELECT publication_revision FROM ot_case WHERE case_id='case-good'")["publication_revision"] == 1


def test_item_validation_failure_rolls_back_pointer_before_recording_blocked(publication, monkeypatch):
    """接口指针更新后的关联校验失败也须回滚该项，不能将半发布内容与BLOCKED回执一起提交。"""

    service, database, scope = publication
    for identity in (1, 2, 3):
        seed_interface(database, identity)
    publish_interface = service.store.publish_interface

    def reject_affected_case(publish_scope, row):
        """真实推进第二接口后模拟关联Case范围校验失败，以验证外层事务回滚。"""

        publish_interface(publish_scope, row)
        if row["baseline_interface_id"] == 2:
            raise ScopeViolationError("PRIVATE-BROKEN-DEPENDENCY")

    monkeypatch.setattr(service.store, "publish_interface", reject_affected_case)
    receipt = service.publish(scope, "interfaces", PublicationRequest(request_id="request-rollback-bad-item", scope="all"))
    assert [item.status for item in receipt.results] == ["PUBLISHED", "BLOCKED", "PUBLISHED"]
    row = database.fetch_one("SELECT current_interface_id,publication_revision,availability FROM ot_baseline_interface WHERE baseline_interface_id=2")
    assert row == {"current_interface_id": None, "publication_revision": 0, "availability": "UNPUBLISHED"}
    assert "PRIVATE" not in receipt.model_dump_json()


def test_database_failure_is_not_persisted_as_terminal_item_failure(publication, monkeypatch):
    """数据库中断保留已提交回执并抛错，恢复后原请求可继续；不能把未知提交包装成永久BLOCKED。"""

    service, database, scope = publication
    for identity in (1, 2, 3):
        seed_interface(database, identity)
    publish_interface = service.store.publish_interface

    def interrupt_database(publish_scope, row):
        """在真实写入第二接口后模拟驱动故障，强制验证该项事务与回执一起回滚。"""

        publish_interface(publish_scope, row)
        if row["baseline_interface_id"] == 2:
            raise sqlite3.OperationalError("database interrupted")

    request = PublicationRequest(request_id="request-infrastructure-retry", scope="all")
    monkeypatch.setattr(service.store, "publish_interface", interrupt_database)
    with pytest.raises(sqlite3.OperationalError, match="database interrupted"):
        service.publish(scope, "interfaces", request)
    receipt = service.store.lock_receipt(request.request_id)
    assert receipt.status == "RUNNING" and [item.item_id for item in receipt.results] == ["1"]
    assert database.fetch_one("SELECT publication_revision FROM ot_baseline_interface WHERE baseline_interface_id=2")["publication_revision"] == 0
    monkeypatch.setattr(service.store, "publish_interface", publish_interface)
    completed = service.publish(scope, "interfaces", request)
    assert completed.status == "COMPLETED" and [item.status for item in completed.results] == ["PUBLISHED"] * 3
    assert [row["publication_revision"] for row in database.fetch_all("SELECT publication_revision FROM ot_baseline_interface")] == [1, 1, 1]


@pytest.mark.parametrize("phase", ["scope", "validation"])
@pytest.mark.parametrize("failure", ["connection", "configuration"])
def test_wrapped_metadata_connection_failure_keeps_publication_retriable(publication, monkeypatch, phase, failure):
    """真实连接边界包装的驱动或凭据故障不能记为坏资产；恢复后同一冻结请求仍能发布。"""

    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2)
    unavailable = True

    def connect(**configuration):
        """只在本地制造连接工厂故障，恢复后返回隔离SQLite连接；不访问MySQL。"""

        if unavailable:
            raise OSError("PRIVATE-CONNECTION-DETAIL")
        return sqlite3.connect(":memory:")

    metadata = MySqlMetadataStore({"host": "unused", "user": "test", "database": "test"}, "test-workspace", connect)
    if failure == "configuration":
        metadata.configuration["password_env"] = "OPENTEST_REVIEW_TEST_MISSING_PASSWORD"
        monkeypatch.delenv("OPENTEST_REVIEW_TEST_MISSING_PASSWORD", raising=False)
    method_name = "get_item" if phase == "scope" else "contract"
    original = getattr(service.store, method_name)

    def read_after_connection(*arguments):
        """让真实发布读取路径经过生产_connect错误包装，保留外围SQL事务与回执实现。"""

        metadata._connect().close()
        return original(*arguments)

    monkeypatch.setattr(service.store, method_name, read_after_connection)
    request = PublicationRequest(request_id=f"request-connect-{phase}-{failure}", scope="all")
    with pytest.raises(MetadataConnectionError) as error:
        service.publish(scope, "interfaces", request)
    assert "PRIVATE" not in str(error.value)
    receipt = service.store.lock_receipt(request.request_id)
    assert receipt.status == "RUNNING" and receipt.results == []
    assert all(row["publication_revision"] == 0 for row in database.fetch_all("SELECT publication_revision FROM ot_baseline_interface"))
    # 配置或连接修复不需要新request_id，也不能因早期失败丢掉原冻结范围。
    unavailable = False
    metadata.configuration.pop("password_env", None)
    completed = service.publish(scope, "interfaces", request)
    assert completed.status == "COMPLETED"
    assert [item.status for item in completed.results] == ["PUBLISHED", "PUBLISHED"]
    metadata.close()


@pytest.mark.parametrize("corrupted_revision", [1, 2])
def test_legacy_body_shape_does_not_block_contract_publication(publication, corrupted_revision):
    """候选或旧版本的legacy正文结构损坏不影响合法独立契约发布，等价内容保留旧版本。"""

    service, database, scope = publication
    seed_interface(database, 1)
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-knowledge-original", scope="all"))
    current = service.store.contract(1, 1)
    database.execute("INSERT INTO ot_interface_contract_version VALUES(1,2,%s,%s,'employee-a')",
        (json.dumps(current["contract"]), json.dumps(current["knowledge"])))
    database.execute("UPDATE ot_interface_draft SET contract_revision=2,expected_publication_revision=1,draft_revision=3,status='READY' WHERE baseline_interface_id=1")
    # 正文只属于可选历史展示；独立契约的身份、Schema和状态均未改变。
    broken = deepcopy(current["knowledge"])
    broken["bodies"]["node-order"] = 123
    database.execute("UPDATE ot_interface_contract_version SET knowledge_json=%s WHERE interface_id=1 AND revision=%s",
        (json.dumps(broken), corrupted_revision))
    seed_interface(database, 2)
    receipt = service.publish(scope, "interfaces", PublicationRequest(request_id="request-knowledge-corrupted", scope="all"))
    assert [(item.item_id, item.status) for item in receipt.results] == [("1", "UNCHANGED"), ("2", "PUBLISHED")]
    assert receipt.results[0].reason_code == "CONTENT_EQUAL"
    row = database.fetch_one("SELECT current_contract_revision,publication_revision FROM ot_baseline_interface WHERE baseline_interface_id=1")
    assert row == {"current_contract_revision": 1, "publication_revision": 1}


def test_contract_comparison_ignores_optional_body_and_preserves_status_semantics(publication):
    """等价判断独立于旧正文；契约存在性和状态仍参与语义比较，READY门禁由发布控制。"""

    service, database, _ = publication
    seed_interface(database, 1)
    content = service.store.contract(1, 1)
    # 相同受阻契约可以语义等价，但不能据此绕过独立的执行准入。
    content["contract"]["status"] = "BLOCKED"
    content["contract"]["blocked_reason"] = "仍需补充测试语义"
    assert equivalent_knowledge(content, deepcopy(content)) is True
    assert equivalent_knowledge(content, {**content, "knowledge": None}) is True
    assert equivalent_knowledge(content, {**content, "contract": None}) is False
    assert equivalent_knowledge(content, {**content, "contract": {**content["contract"], "status": "READY", "blocked_reason": ""}}) is False


def generation_payload():
    """构造含两条不同私有输入的同批Case；模型字段均为真实有限DSL格式。"""

    # 让同一编译产物同时含公开和私有标记，防止只验证接口ID却泄漏整个模板。
    evidence = {"source_system_id": "orders", "path": "Order.java"}
    oracle = {"oracle_id": "oracle-ok", "channel": "response", "assertions": [{"actual_path": "id", "operator": "exists"}]}
    variants = [{"variant_id": "case-variant-v4-" + digit * 20, "template_id": "query-order", "ordinal": index,
                 "parameter_values": {}, "request_values": {"id": marker}, "data_calls": [], "oracles": [oracle]}
                for index, digit, marker in [(1, "a", "public-order"), (2, "b", "PRIVATE-SIBLING")]]
    template = {"template_id": "query-order", "title": "订单查询", "coverage_kind": "business", "parameters": [],
                "request_bindings": [{"field": "id", "source": {"kind": "literal", "value": "private-template-values"}}],
                "combination": "each", "oracles": [oracle], "evidence": [evidence]}
    return {"generation_id": "case-template-generation-" + "a" * 20, "system_id": "orders", "operation_id": "query-1",
            "source_scan_id": "scan-1", "coverage_id": "coverage:query", "runtime_registry_version": "runtime-functions/v1",
            "value_registry_version": "value-functions/v1", "status": "READY", "input_contract": contract_payload(),
            "submission": {"data_functions": [], "case_templates": [template], "unresolved": []}, "variants": variants,
            "baseline_id": "baseline-one", "owner_user_id": "employee-a",
            "case_bindings": [{"case_id": "case-public", "variant_id": variants[0]["variant_id"], "knowledge_dependencies": [{"baseline_interface_id": 1, "interface_id": 1, "contract_revision": 1}]},
                              {"case_id": "case-private", "variant_id": variants[1]["variant_id"], "knowledge_dependencies": [{"baseline_interface_id": 1, "interface_id": 1, "contract_revision": 1}]}]}


def test_single_case_projection_hides_private_sibling_and_old_author_content(publication):
    """同批只发布一项不能泄漏私有变体或完整DSL；已发布草稿不授权读取旧内容。"""

    # 发布仅选择首项，读取者换成员工B；任何整批泄漏都会带出PRIVATE标记。
    service, database, scope = publication
    seed_interface(database, 1)
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-interface", scope="all"))
    payload = generation_payload()
    generation = CaseTemplateGenerationV4.model_validate(payload)
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                     (generation.generation_id, generation.model_dump_json()))
    database.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES('case-public',1)")
    database.execute("INSERT INTO ot_case_draft VALUES('case-public','employee-a',%s,%s,0,1,'READY',NULL)",
                     (generation.generation_id, generation.variants[0].variant_id))
    result = service.publish(scope, "cases", PublicationRequest(request_id="request-case-pub1", scope="all"))
    assert result.results[0].status == "PUBLISHED"
    other = scope.model_copy(update={"user_id": "employee-b"})
    visible = service.get_case(other, "case-public")
    serialized = visible.model_dump_json()
    assert "public-order" in serialized
    assert "PRIVATE-SIBLING" not in serialized
    assert "private-template-values" not in serialized
    assert "submission" not in serialized
    with pytest.raises(KnowledgeNotFoundError):
        service.get_case(scope, "case-public", "mine")
    with pytest.raises(KnowledgeNotFoundError):
        service.get_case(other, "case-private")


def test_contract_metadata_normalization_never_removes_business_schema_fields():
    """名为source_commit或created_at的业务字段必须参与变化判断，不能被泛化清理误删。"""

    # 来源字段可忽略，但相同名称出现在真实请求Schema时必须仍影响兼容判断。
    original = contract_payload()
    original["request_schema"]["properties"]["source_commit"] = {"type": "string", "const": "old"}
    revised = deepcopy(original)
    revised["source_scan_id"] = "scan-new"
    assert contract_test_content(original) == contract_test_content(revised)
    revised["request_schema"]["properties"]["source_commit"]["const"] = "new"
    assert contract_test_content(original) != contract_test_content(revised)


def test_case_draft_accepts_generation_with_workstation_source_paths(publication, tmp_path):
    """共享存储清除源码机器目录后，保存草稿仍须识别同一固定Generation，不能把本机投影当内容变化。"""

    service, database, scope = publication
    seed_interface(database, 1)
    payload = generation_payload()
    payload["source_scopes"] = [{
        "source_system_id": "orders", "source_scan_id": "scan-1",
        "source_baseline": {"source_path": "", "commit": "a" * 40, "branch": "main",
                            "revision": "opentest/baseline/" + "a" * 40},
        "selected_operation_ids": ["query-1"],
    }]
    original = CaseTemplateGenerationV4.model_validate(payload)
    # 持久化载荷不含机器目录；读取端按本机source-bindings重新投影，两者只差路径。
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                     (original.generation_id, json.dumps(portable_scope_payload(original))))
    (tmp_path / ".opentest").mkdir()
    (tmp_path / ".opentest" / "source-bindings.json").write_text(json.dumps({"orders": "/work/orders"}), encoding="utf-8")
    hydrated = hydrate_scope_record(original, tmp_path)
    assert hydrated != original and hydrated.source_scopes[0].source_baseline.source_path == "/work/orders"
    update = CaseDraftUpdate(binding=original.case_bindings[0], baseline_interface_id=1,
                             expected_draft_revision=0, expected_publication_revision=0)
    assert service.save_case_drafts(scope, hydrated, [update]) == ["case-public"]
    # 本机路径不参与身份，实际业务字段变化仍必须拒绝。
    changed = hydrated.model_copy(update={"coverage_id": "coverage:other"})
    with pytest.raises(KnowledgeValidationError, match="固定编译产物"):
        service.save_case_drafts(scope, changed, [update])


def seed_published_case(service, database, scope):
    """建立一份只公开首项的合法Generation，返回固定内容便于验收执行选择和编辑隔离。"""

    # 仅把第一条Case放进草稿与发布集合，第二条只存在不可变Generation中。
    seed_interface(database, 1)
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-interface-setup", scope="all"))
    generation = CaseTemplateGenerationV4.model_validate(generation_payload())
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                     (generation.generation_id, generation.model_dump_json()))
    database.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES('case-public',1)")
    database.execute("INSERT INTO ot_case_draft VALUES('case-public','employee-a',%s,%s,0,1,'READY',NULL)",
                     (generation.generation_id, generation.variants[0].variant_id))
    service.publish(scope, "cases", PublicationRequest(request_id="request-case-setup", scope="all"))
    return generation


def seed_equivalent_review_draft(service, database, scope):
    """为已发布Case建立内容相同的新员工草稿并标历史需复核，返回原共享Generation。"""

    original = seed_published_case(service, database, scope)
    candidate = original.model_copy(update={"generation_id": "case-template-generation-" + "c" * 20})
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
        (candidate.generation_id, candidate.model_dump_json()))
    # 复核必须走真实的草稿CAS和显式发布入口，不能靠直接推进共享指针消除影响。
    current = service.store.get_item(scope, "cases", "case-public")
    service.save_case_drafts(scope, candidate, [CaseDraftUpdate(binding=candidate.case_bindings[0],
        baseline_interface_id=1, expected_draft_revision=current["draft_revision"], expected_publication_revision=1)])
    service.store.mark_impact("case-public", "NEEDS_UPDATE", {"reason_code": "MIGRATED_KNOWLEDGE_REVIEW"})
    return original


@pytest.mark.parametrize("reason", ["MIGRATED_KNOWLEDGE_REVIEW", "MIGRATED_SCAN_SCOPE_REVIEW", "REVIEW_REQUIRED"])
def test_equal_case_explicit_publication_clears_review_without_advancing_shared_version(publication, reason):
    """等价草稿完整复核后可执行；保留共享身份版本，旧发布回执重放不能解除后来的新影响。"""

    service, database, scope = publication
    original = seed_equivalent_review_draft(service, database, scope)
    service.store.mark_impact("case-public", "NEEDS_UPDATE", {"reason_code": reason})
    before = database.fetch_one("SELECT * FROM ot_case WHERE case_id='case-public'")
    request = PublicationRequest(request_id="request-equal-review", scope="all")
    receipt = service.publish(scope, "cases", request)
    assert receipt.results[0].status == "UNCHANGED" and receipt.results[0].publication_revision == 1
    after = database.fetch_one("SELECT * FROM ot_case WHERE case_id='case-public'")
    for field in ("current_generation_id", "current_variant_id", "publication_revision", "knowledge_dependencies_json",
                  "published_by_user_id", "published_at"):
        assert after[field] == before[field]
    assert after["impact_status"] == "CURRENT" and not json.loads(after["impact_details_json"])
    assert service.require_executable(scope, "case-public", "published").generation_id == original.generation_id
    assert service.list_cases(scope, "mine") == []
    assert service.publish(scope, "cases", request) == receipt
    # 同request_id仅重放当时的回执；后续影响必须由另一次明确复核解决。
    service.store.mark_impact("case-public", "NEEDS_UPDATE", {"reason_code": "LATER_KNOWLEDGE_CHANGE"})
    assert service.publish(scope, "cases", request) == receipt
    assert service.get_case(scope, "case-public").impact_status == "NEEDS_UPDATE"


@pytest.mark.parametrize("legacy_body", ["missing", "blank", "migration_marker", "legacy_marker", "changed"])
def test_ready_contract_without_legacy_body_can_be_saved_published_and_used(publication, legacy_body):
    """本人READY契约无需历史正文即可存草稿、发布及显式复核Case，迁移标记本身保持原样。"""

    service, database, scope = publication
    original = seed_equivalent_review_draft(service, database, scope)
    stored = database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version WHERE interface_id=1")
    bundle = json.loads(stored["knowledge_json"])
    # 模拟真实迁移记录的各种旧正文；仅明确发布行为解除Case复核，不后台清除历史标记。
    if legacy_body == "missing":
        bundle = None
    elif legacy_body == "blank":
        bundle["bodies"]["node-order"] = "  \n"
    elif legacy_body == "changed":
        bundle["bodies"]["node-order"] = "不同的历史实现叙述，不属于独立契约"
    else:
        bundle["nodes"][0]["metadata"] = ({"migration_requires_review": True} if legacy_body == "migration_marker" else
            {"limitation": "历史迁移仅冻结已有接口契约，未重新分析实现。"})
    raw_bundle = json.dumps(bundle) if bundle is not None else None
    database.execute("UPDATE ot_interface_contract_version SET knowledge_json=%s WHERE interface_id=1", (raw_bundle,))
    row = service.store.get_item(scope, "interfaces", "1")
    saved = service.save_interface_draft(scope, InterfaceDraftUpdate(operation_id="query-1", interface_id=1,
        contract_revision=1, status="READY", expected_draft_revision=row["draft_revision"], expected_publication_revision=1))
    assert saved["status"] == "READY"
    interface_receipt = service.publish(scope, "interfaces", PublicationRequest(request_id="request-contract-only", scope="all"))
    assert interface_receipt.results[0].status == "UNCHANGED"
    assert service.get_case(scope, "case-public").impact_status == "NEEDS_UPDATE"
    receipt = service.publish(scope, "cases", PublicationRequest(request_id="request-review-contract-only", scope="all"))
    assert receipt.results[0].status == "UNCHANGED"
    assert service.require_executable(scope, "case-public", "published").generation_id == original.generation_id
    assert database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version WHERE interface_id=1")["knowledge_json"] == raw_bundle


@pytest.mark.parametrize("problem", ["missing_contract", "blocked", "wrong_entry", "wrong_scan", "removed", "changed"])
def test_equal_case_review_cannot_bypass_invalid_or_incompatible_contract(publication, problem):
    """取消正文门禁后仍拒绝缺契约、受阻状态、错入口/扫描、移除和真实Schema变化。"""

    service, database, scope = publication
    original = seed_equivalent_review_draft(service, database, scope)
    current = service.store.contract(1, 1)
    # 在真实固定契约记录注入业务失败，验证显式发布也不能绕过契约和来源边界。
    contract = deepcopy(current["contract"])
    if problem == "removed":
        database.execute("UPDATE ot_baseline_interface SET availability='REMOVED' WHERE baseline_interface_id=1")
    elif problem == "changed":
        contract["contract_revision"] = 2
        contract["response_schema"] = {"type": "object", "properties": {"id": {"type": "integer"}}}
        database.execute("INSERT INTO ot_interface_contract_version VALUES(1,2,%s,NULL,'employee-a')", (json.dumps(contract),))
        database.execute("UPDATE ot_baseline_interface SET current_contract_revision=2 WHERE baseline_interface_id=1")
    else:
        if problem == "missing_contract":
            contract = None
        elif problem == "blocked":
            contract.update(status="BLOCKED", blocked_reason="请求字段类型尚未解析")
        elif problem == "wrong_entry":
            contract["target_id"] = "query-other"
        else:
            contract["source_scan_id"] = "scan-other"
        database.execute("UPDATE ot_interface_contract_version SET contract_json=%s WHERE interface_id=1",
            (json.dumps(contract) if contract is not None else None,))
    receipt = service.publish(scope, "cases", PublicationRequest(request_id="request-review-blocked", scope="all"))
    assert receipt.results[0].status == "BLOCKED"
    case = service.get_case(scope, "case-public")
    assert case.impact_status == "NEEDS_UPDATE" and case.publication_revision == 1
    assert case.generation_id == original.generation_id
    assert len(service.list_cases(scope, "mine")) == 1
    with pytest.raises(KnowledgeValidationError):
        service.require_executable(scope, "case-public", "published")


def test_equal_case_review_impact_rolls_back_with_failed_publication(publication, monkeypatch):
    """复核清理与草稿关闭、回执使用同一事务，后续写入失败不能留下可执行的半次发布。"""

    service, database, scope = publication
    seed_equivalent_review_draft(service, database, scope)

    def fail_mark_published(current_scope, kind, item_id):
        """验证影响已在当前事务清理后制造保存故障，供外层逐项回滚。"""

        assert service.get_case(current_scope, item_id).impact_status == "CURRENT"
        raise KnowledgeValidationError("模拟草稿收尾失败")

    # 故障发生在影响状态更新之后，确保正常BLOCKED回执不遗留半次发布。
    monkeypatch.setattr(service.store, "mark_published", fail_mark_published)
    receipt = service.publish(scope, "cases", PublicationRequest(request_id="request-review-rollback", scope="all"))
    assert receipt.results[0].status == "BLOCKED"
    assert service.get_case(scope, "case-public").impact_status == "NEEDS_UPDATE"
    assert len(service.list_cases(scope, "mine")) == 1


def test_execution_history_requires_exact_selection_and_preserves_single_case_status(publication):
    """混合执行只公开当前Case的状态和证据；相同Generation的未选项、错基准与另一环境全部隔离。"""

    from opentest.domain.case_template_v4 import CaseGenerationExecutionV4

    # 同时写入混合执行、未选项、另一环境和错误基准，验证过滤发生在返回统计之前。
    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    selected = {"case_id": "case-public", "generation_id": generation.generation_id,
                "variant_id": generation.variants[0].variant_id}
    other = {"case_id": "case-private", "generation_id": generation.generation_id,
             "variant_id": generation.variants[1].variant_id}
    executions = []
    for digit, choices, environment, indexed_baseline in [("a", [selected, other], "qa", "baseline-one"),
            ("b", [other], "qa", "baseline-one"), ("c", [selected], "uat", "baseline-one"),
            ("d", [selected], "qa", "different-baseline")]:
        execution = CaseGenerationExecutionV4(execution_id="case-generation-execution-" + digit * 20,
            generation_id=generation.generation_id, system_id="orders", baseline_id="baseline-one", owner_user_id="employee-a",
            selected_cases=choices, environment_id=environment, status="PARTIAL", safe_error="PRIVATE-BATCH-ERROR",
            variant_results=[{"variant_id": generation.variants[0].variant_id, "status": "COMPLETED"},
                             {"variant_id": generation.variants[1].variant_id, "status": "FAILED", "error": "PRIVATE-ERROR"}])
        database.execute("INSERT INTO ot_execution VALUES(%s,'case','orders',%s,%s,%s,%s,'2026-10-21')",
            (execution.execution_id, indexed_baseline, generation.generation_id, environment, execution.model_dump_json()))
        executions.append(execution)
    visible = service.list_case_executions(scope, "case-public", "qa")
    assert len(visible) == 1
    assert visible[0]["status"] == "COMPLETED"
    assert "PRIVATE" not in json.dumps(visible, default=str)
    with pytest.raises(KnowledgeNotFoundError):
        service.case_execution(scope, "case-public", executions[1].execution_id)
    with pytest.raises(KnowledgeNotFoundError):
        service.case_execution(scope, "case-public", executions[3].execution_id)


def test_knowledge_reads_only_current_view_and_requires_disambiguation(publication):
    """同名节点不猜版本；未发布他人正文及被替换节点不能由旧ID读取。"""

    # 用相同node ID和不同正文制造真实歧义，不能按查询顺序任取一个。
    service, database, scope = publication
    seed_interface(database, 1)
    seed_interface(database, 2, summary="第二接口的不同正文")
    seed_interface(database, 3, owner="employee-b", summary="他人尚未发布的正文")
    service.publish(scope, "interfaces", PublicationRequest(request_id="request-node-setup", scope="all"))
    catalog = service.knowledge_catalog(scope)
    assert {item["baseline_interface_id"] for item in catalog["items"]} == {1, 2}
    with pytest.raises(IdempotencyConflictError, match="baseline_interface_id"):
        service.knowledge_node(scope, "node-order")
    assert service.knowledge_node(scope, "node-order", "published", 1)["content"] == "订单查询"
    with pytest.raises(KnowledgeNotFoundError):
        service.knowledge_node(scope, "node-order", "published", 3)
    assert service.knowledge_catalog(scope, "mine")["items"] == []
    database.execute("UPDATE ot_baseline_interface SET availability='REMOVED' WHERE baseline_interface_id=1")
    with pytest.raises(KnowledgeNotFoundError):
        service.knowledge_node(scope, "node-order", "published", 1)


def test_private_baseline_context_is_not_exposed_before_source_upload(publication):
    """仅知道别人尚未完成上传的基准ID不能读取其背景；未知作者的历史成果仍正常保留。"""

    from opentest.domain.errors import ScopeViolationError

    # 未完成上传的他人基准属于创建过程；迁入未知作者历史基准仍必须共享。
    service, database, scope = publication
    database.execute("UPDATE ot_code_baseline SET created_by_user_id='employee-b' WHERE baseline_id='baseline-one'")
    with pytest.raises(ScopeViolationError):
        service.knowledge_catalog(scope)
    database.execute("UPDATE ot_code_baseline SET created_by_user_id=NULL WHERE baseline_id='baseline-one'")
    assert service.knowledge_catalog(scope)["baseline_id"] == "baseline-one"


def test_single_case_edit_pins_only_selected_parameter_values(publication):
    """从组合模板编辑单Case时参数值必须固定，不把其他未发布候选参数一起复制。"""

    from opentest.application.publication import project_case, single_case_submission

    # 单Case编辑需要实际编译值，不能继承可展开出其他私有变体的参数引用。
    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    payload = generation.model_dump(mode="json")
    template = payload["submission"]["case_templates"][0]
    template["request_bindings"][0]["source"] = {"kind": "parameter", "name": "order_id"}
    payload["variants"][0]["parameter_values"] = {"order_id": "PUBLIC-ORDER"}
    generation = CaseTemplateGenerationV4.model_validate(payload)
    selection = service.store.get_item(scope, "cases", "case-public")
    case = project_case(generation, selection, "published")
    draft = single_case_submission(generation, case)
    assert len(draft.case_templates) == 1
    assert draft.case_templates[0].request_bindings[0].source.kind == "literal"
    assert draft.case_templates[0].request_bindings[0].source.value == "PUBLIC-ORDER"
    assert "PRIVATE-SIBLING" not in draft.model_dump_json()


def test_coverage_seed_from_other_employee_uses_only_selected_case_and_fresh_ids(publication, tmp_path):
    """别人共享的单Case可创建本人补充任务，但原私有同批内容和原草稿身份均不能被复制或替换。

    publication提供共享权限夹具，tmp_path隔离新handoff；变体保留真实种子模板身份以模拟编译产物。
    """

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
    from opentest.application.auth import bind_authenticated_identity
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.domain.auth import AuthenticatedIdentity, EmployeeIdentity
    from opentest.domain.shared_workspace import CaseSelection, InterfaceKnowledgeRef
    from test_case_template_v4_revision import _handoff

    # 员工B只见员工A共享的首项；种子编译不得复用A的Case草稿身份。
    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = service.knowledge_store
    engine.generations = SimpleNamespace(get=Mock(return_value=generation))
    engine.handoffs = CaseTemplateHandoffStoreV4(tmp_path / "handoffs")
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "baseline_id": "baseline-one", "owner_user_id": "employee-b", "draft_submission": None,
        "source_scopes": [_handoff(tmp_path).source_scopes[0].model_copy(update={"source_system_id": "orders"})],
        "case_bindings": [], "knowledge_dependencies": [InterfaceKnowledgeRef(
            baseline_interface_id=1, interface_id=1, contract_revision=1)]})
    engine.handoffs.write(handoff)
    selected = CaseSelection(case_id="case-public", generation_id=generation.generation_id,
                             variant_id=generation.variants[0].variant_id)
    identity = AuthenticatedIdentity(EmployeeIdentity(user_id="employee-b", name="其他员工"), "user_bearer")
    with bind_authenticated_identity(identity):
        seeded = engine.seed_coverage_cases(handoff.handoff_id, [selected])
        restored = engine.seed_coverage_cases(handoff.handoff_id, [selected])
        assert restored == seeded
        assert seeded.owner_user_id == "employee-b"
        assert seeded.case_bindings == [] and seeded.case_edit_references == []
        assert seeded.editing_case_id == ""
        assert len(seeded.draft_submission.case_templates) == 1
        assert "PRIVATE-SIBLING" not in seeded.draft_submission.model_dump_json()
        # 真实编译输出引用重命名后的种子模板，不能把原模板身份冒充成覆盖种子的编译结果。
        seeded_variant = generation.variants[0].model_copy(update={
            "template_id": seeded.draft_submission.case_templates[0].template_id})
        frozen = engine._freeze_case_bindings(seeded, [seeded_variant])
    assert frozen.case_bindings[0].case_id not in {"case-public", "case-private"}
    assert service.get_case(scope, "case-public").generation_id == generation.generation_id
    assert service.list_cases(scope.model_copy(update={"user_id": "employee-b"}), "mine") == []


def test_compile_receipt_replay_never_returns_replaced_generation(publication, tmp_path):
    """编译请求重放可复用内部固定回执，但外部响应只能看到仍当前的单Case，不能恢复整份旧DSL。"""

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.application.foundation import OpenTestApplication
    from opentest.domain.case_template_v4 import CaseTemplatePublicationRequest
    from test_case_template_v4_revision import _handoff

    # 同一内部编译回执在共享指针更新前后重放，外部可见结果必须跟随当前指针。
    service, database, scope = publication
    generation = seed_published_case(service, database, scope).model_copy(update={"execution_mode": "generate_only"})
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = service.knowledge_store
    engine.publish = Mock(return_value=generation)
    engine.handoffs = CaseTemplateHandoffStoreV4(tmp_path / "handoffs")
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "baseline_id": "baseline-one", "owner_user_id": "employee-a", "generation_id": generation.generation_id,
        "case_bindings": generation.case_bindings, "status": "COMPLETED"})
    engine.handoffs.write(handoff)
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.case_template_v4 = engine
    application._sync_case_task = Mock(return_value=SimpleNamespace(task_id="task-example", status="COMPLETED",
        active_handoff_id=handoff.handoff_id, system_id="orders"))
    application.coverage_assistance = SimpleNamespace(projection=Mock(return_value=None))
    request = CaseTemplatePublicationRequest(request_id="compile-replay-one", expected_revision=handoff.revision, mode="complete")
    first = application.publish_case_template_v4(handoff.handoff_id, request)
    assert [item["case_id"] for item in first["cases"]] == ["case-public"]
    assert "generation" not in first and "execution" not in first
    assert "PRIVATE-SIBLING" not in json.dumps(first)
    replacement = generation.model_copy(update={"generation_id": "case-template-generation-" + "b" * 20})
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-b',%s)",
        (replacement.generation_id, replacement.model_dump_json()))
    database.execute("UPDATE ot_case SET current_generation_id=%s WHERE case_id='case-public'", (replacement.generation_id,))
    replay = application.publish_case_template_v4(handoff.handoff_id, request)
    assert replay["cases"] == []
    assert "generation" not in replay and "PRIVATE-SIBLING" not in json.dumps(replay)


def test_terminal_prepare_replay_uses_current_cases_instead_of_saved_handoff(publication, tmp_path):
    """创建请求在终态重放时不返回已保存整批草稿；共享Case被替换后也不能由该入口重新读取。"""

    from unittest.mock import Mock
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.application.foundation import OpenTestApplication
    from test_case_template_v4_revision import _handoff

    service, database, scope = publication
    generation = seed_published_case(service, database, scope)
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "baseline_id": "baseline-one", "owner_user_id": "employee-a", "generation_id": generation.generation_id,
        "case_bindings": generation.case_bindings, "status": "COMPLETED"})
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.case_template_v4 = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    application.case_template_v4.store = service.knowledge_store
    task = Mock()
    task.task_id = "task-terminal"
    task.model_dump.return_value = {"task_id": task.task_id, "status": "completed"}

    # 初次终态仅返回当前共享单项，不把同批私有兄弟Case夹带到幂等响应。
    response = application._case_preparation_result(task, handoff)
    assert response["handoff"] is None
    assert [item["case_id"] for item in response["cases"]] == ["case-public"]
    assert "PRIVATE-SIBLING" not in json.dumps(response)
    database.execute("UPDATE ot_case SET current_generation_id=NULL WHERE case_id='case-public'")
    replay = application._case_preparation_result(task, handoff)
    assert replay["handoff"] is None and replay["cases"] == []


@pytest.mark.parametrize("intent", ["continue", "regenerate_latest"])
@pytest.mark.parametrize("status", ["COMPLETED", "PARTIAL", "BLOCKED"])
def test_terminal_shared_task_cannot_reopen_hidden_cases_or_switch_uat(publication, tmp_path, intent, status):
    """共享终态任务的两种旧续跑入口都必须在创建后继之前拒绝，隐藏Case及UAT冻结值不变。"""

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.application.foundation import OpenTestApplication
    from opentest.domain.case_template_v4 import CaseTemplateContinuationRequest
    from opentest.domain.errors import KnowledgeValidationError
    from test_case_template_v4_revision import _handoff

    service, database, scope = publication
    generation = seed_published_case(service, database, scope).model_copy(update={"environment_id": "uat"})
    # 模拟整批含私有兄弟项，原公开项也已被替代；旧不可变Generation仍留库。
    database.execute("UPDATE ot_case SET current_generation_id=NULL WHERE case_id='case-public'")
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.generations = SimpleNamespace(get=Mock(return_value=generation))
    engine.handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    handoff = _handoff(tmp_path, status=status).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "baseline_id": "baseline-one", "owner_user_id": "employee-a", "environment_id": "uat",
        "generation_id": generation.generation_id, "draft_submission": generation.submission})
    engine.handoffs.write(handoff)
    task = SimpleNamespace(operation="case-generation", active_handoff_id=handoff.handoff_id,
                           result={"baseline_id": "baseline-one"})
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.case_template_v4 = engine
    application._prepare_case_successor_task = Mock()
    engine._new_successor_handoff = Mock()
    with pytest.raises(KnowledgeValidationError, match="单个Case"):
        application._continue_case_task_workflow(task, "shared-terminal-continue", intent, 0)
    with pytest.raises(KnowledgeValidationError, match="单个Case"):
        engine.continue_generation("orders", generation.generation_id, CaseTemplateContinuationRequest(
            request_id="direct-shared-continue", expected_revision=0, intent=intent))
    application._prepare_case_successor_task.assert_not_called()
    engine._new_successor_handoff.assert_not_called()
    assert engine.handoffs.get(handoff.handoff_id) == handoff
    assert engine.handoffs.get(handoff.handoff_id).environment_id == "uat"
    assert service.list_cases(scope) == []
    assert service.list_cases(scope, "mine") == []
    assert "PRIVATE-SIBLING" in generation.model_dump_json()


def test_active_shared_draft_resumes_same_uat_task_without_successor(tmp_path):
    """共享草稿失败仍能在原身份、基准、环境和源码范围内恢复，不被终态门禁误伤。"""

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.application.foundation import OpenTestApplication
    from test_case_template_v4_revision import _handoff, _service, _compiled, _submission

    # 使用真实handoff持久化与恢复状态机，不能仅验证应用转发了一次调用。
    engine, handoffs, generations = _service(tmp_path, _compiled())
    handoff = _handoff(tmp_path, status="FAILED", revision=2).model_copy(update={
        "baseline_id": "baseline-one", "owner_user_id": "employee-a", "environment_id": "uat",
        "draft_submission": _submission(), "recoverable": True})
    handoffs.write(handoff)
    task = SimpleNamespace(operation="case-generation", active_handoff_id=handoff.handoff_id,
                           result={"baseline_id": "baseline-one"})
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.case_template_v4 = engine
    application._sync_case_task = Mock(return_value=task)
    application._case_preparation_result = Mock(return_value={"resumed": True})
    application._prepare_case_successor_task = Mock()
    assert application._continue_case_task_workflow(task, "resume-shared-draft", "continue", 2) == {"resumed": True}
    restored = handoffs.get(handoff.handoff_id)
    assert restored.status == "WAITING_FOR_AGENT" and restored.revision == 3
    assert restored.environment_id == "uat" and restored.baseline_id == handoff.baseline_id
    assert restored.owner_user_id == handoff.owner_user_id and restored.source_scopes == handoff.source_scopes
    assert restored.successor_handoff_id == "" and restored.draft_submission == handoff.draft_submission
    application._prepare_case_successor_task.assert_not_called()
    generations.write.assert_not_called()


@pytest.mark.parametrize("dependency_kind", ["oracle", "query", "data", "cleanup"])
def test_single_case_revision_refreshes_used_dependency_and_drops_old_target_scan(publication, tmp_path, dependency_kind):
    """单项修订映射Runtime别名及仅清理依赖；同commit补充目标契约后使用新扫描。"""

    from types import SimpleNamespace
    from unittest.mock import Mock
    from opentest.application.case_template_v4 import CaseTemplateV4Service
    from opentest.application.case_template_registries import CaseTemplateRegistryLoader
    from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest
    from opentest.domain.models import OperationCapability, SourceBaseline
    from opentest.domain.shared_workspace import CaseSelection, InterfaceKnowledgeRef
    from test_case_template_v4_revision import _handoff

    service, database, scope = publication
    seed_interface(database, 2)
    generation = seed_published_case(service, database, scope)
    # 分别覆盖函数ID同名、数据库:query/:data及仅清理引用，不能只验证同名Oracle的巧合。
    base_scope = _handoff(tmp_path).source_scopes[0]
    target_scope = base_scope.model_copy(update={"source_system_id": "orders", "source_scan_id": "scan-1",
        "selected_operation_ids": ["query-1"]})
    provider_scope = target_scope.model_copy(update={"source_scan_id": "scan-2", "selected_operation_ids": ["query-2"]})
    original = generation.model_dump(mode="json")
    if dependency_kind == "oracle":
        original["variants"][0]["oracles"][0].update({"channel": "operation", "function_id": "query-2"})
    elif dependency_kind in {"query", "data"}:
        statement = "SELECT id FROM orders WHERE id=:id LIMIT 1" if dependency_kind == "query" else "UPDATE orders SET status=:status WHERE id=:id"
        original["submission"]["data_functions"] = [{"name": "prepare_order", "description": "按实际数据库准备订单数据",
            "steps": [{"step_id": "lookup", "operation": "runtime_call", "function_id": f"query-2:{dependency_kind}",
                "arguments": {"statement": {"kind": "literal", "value": statement},
                    "parameters": {"kind": "literal", "value": {"id": 1, "status": "READY"}},
                    "purpose": {"kind": "literal", "value": "case"}}}],
            "outputs": [{"output_name": "row_count", "step_id": "lookup", "path": "row_count"}],
            "evidence": [{"source_system_id": "orders", "path": "OrderRepository.java"}]}]
        call = {"call_id": "prepared_order", "function_name": "prepare_order", "arguments": {}}
        original["variants"][0]["data_calls"] = [call]
        original["submission"]["case_templates"][0]["data_calls"] = [call]
    else:
        cleanup = {"cleanup_id": "clean-order", "operation_id": "query-2", "arguments": {},
                   "evidence": [{"source_system_id": "orders", "path": "OrderCleanup.java"}]}
        original["variants"][0]["cleanup"] = cleanup
        original["submission"]["case_templates"][0]["cleanup"] = cleanup
    original["case_bindings"][0]["knowledge_dependencies"].append(
        {"baseline_interface_id": 2, "interface_id": 2, "contract_revision": 1})
    original["source_scopes"] = [target_scope.model_dump(mode="json"), provider_scope.model_dump(mode="json")]
    generation = CaseTemplateGenerationV4.model_validate(original)
    database.execute("UPDATE ot_case_generation SET generation_json=%s", (generation.model_dump_json(),))
    database.execute("UPDATE ot_case SET knowledge_dependencies_json=%s WHERE case_id='case-public'",
                     (json.dumps(original["case_bindings"][0]["knowledge_dependencies"]),))

    # B约束改变，A在同commit重扫后补充用途说明；两者均为独立契约变化，不能只改正文制造新版本。
    stored_bundle = database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version WHERE interface_id=2")["knowledge_json"]
    new_contract = {**contract_payload("新的依赖约束"), "contract_revision": 2, "source_scan_id": "scan-2", "target_id": "query-2"}
    database.execute("INSERT INTO ot_interface_contract_version VALUES(2,2,%s,%s,'employee-a')",
                     (json.dumps(new_contract), stored_bundle))
    database.execute("UPDATE ot_interface_draft SET contract_revision=2,status='READY',draft_revision=2,expected_publication_revision=1 WHERE baseline_interface_id=2")
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id) VALUES('scan-3','baseline-one')")
    database.execute("INSERT INTO ot_interface VALUES(3,'orders','scan-3','query-1')")
    target_contract = {**contract_payload("补充目标入口用途"), "source_scan_id": "scan-3", "target_id": "query-1"}
    database.execute("INSERT INTO ot_interface_contract_version VALUES(3,1,%s,%s,'employee-a')",
                     (json.dumps(target_contract), stored_bundle))
    database.execute("UPDATE ot_interface_draft SET interface_id=3,status='READY',draft_revision=2,expected_publication_revision=1 WHERE baseline_interface_id=1")
    changed = service.publish(scope, "interfaces", PublicationRequest(request_id="request-new-knowledge", scope="all"))
    assert all(item.status == "PUBLISHED" for item in changed.results)
    assert service.get_case(scope, "case-public").impact_status == "NEEDS_UPDATE"

    current_target = target_scope.model_copy(update={"source_scan_id": "scan-3"})
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "source_scan_id": "scan-3", "baseline_id": "baseline-one", "owner_user_id": "employee-a", "environment_id": "uat",
        "source_scopes": [current_target], "knowledge_dependencies": [InterfaceKnowledgeRef(
            baseline_interface_id=1, interface_id=3, contract_revision=1)]})
    capabilities = {scan: OperationCapability(operation_id=operation, system_id="orders", business_name=operation,
        kind="DATABASE" if operation == "query-2" and dependency_kind in {"query", "data"} else "FACADE",
        mutability="READ_ONLY", source_scan_id=scan, executable=True)
        for scan, operation in [("scan-1", "query-1"), ("scan-2", "query-2"), ("scan-3", "query-1")]}

    def derive(system_id, scan_id, **kwargs):
        """测试目录只根据被请求的固定扫描返回实际操作，暴露旧目标范围重复的错误。"""

        return [capabilities[scan_id]]

    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = service.knowledge_store
    engine.store.get_system = Mock()
    engine.generations = SimpleNamespace(get=Mock(return_value=generation))
    engine.runtime = SimpleNamespace(operation_catalog=SimpleNamespace(derive=derive))
    engine.operation_contracts = None  # 本测试隔离依赖绑定，分类叠加由专门的版本回归覆盖。
    engine.registries = CaseTemplateRegistryLoader()
    engine.handoffs = Mock()
    engine.artifacts = SimpleNamespace(read=Mock(return_value=SimpleNamespace(baseline=SourceBaseline(source_path=str(tmp_path), commit="a" * 40))))
    request = CaseTemplateGenerationStartRequest(operation_id="query-1", request_id="single-case-revision",
        editing_case=CaseSelection(case_id="case-public", generation_id=generation.generation_id,
                                   variant_id=generation.variants[0].variant_id))
    seeded = engine._seed_single_case_revision(handoff, request)
    assert {item.interface_id: item.contract_revision for item in seeded.knowledge_dependencies} == {3: 1, 2: 2}
    assert {(item.source_scan_id, tuple(item.selected_operation_ids)) for item in seeded.source_scopes} == {
        ("scan-3", ("query-1",)), ("scan-2", ("query-2",))}
    assert engine._case_dependency_operation(seeded, "query-1")[0].source_scan_id == "scan-3"
    assert seeded.environment_id == "uat" and "PRIVATE-SIBLING" not in seeded.draft_submission.model_dump_json()
    # 最终编译绑定也必须使用相同映射，不能seed保留了依赖却在发布前再次丢掉数据库或清理引用。
    seeded = engine._freeze_case_bindings(seeded.model_copy(update={"case_bindings": []}), [generation.variants[0]])
    assert {item.interface_id: item.contract_revision for item in seeded.case_bindings[0].knowledge_dependencies} == {3: 1, 2: 2}

    # 用新冻结引用提交个人草稿并真实发布，证明待更新不是只能阅读而不能消除的死状态。
    updated_generation = generation.model_copy(update={"generation_id": "case-template-generation-" + "d" * 20,
        "source_scan_id": "scan-3", "environment_id": "uat", "source_scopes": seeded.source_scopes,
        "submission": seeded.draft_submission, "variants": [generation.variants[0]], "case_bindings": seeded.case_bindings})
    database.execute("INSERT INTO ot_case_generation VALUES(%s,'orders','baseline-one','employee-a',%s)",
                     (updated_generation.generation_id, updated_generation.model_dump_json()))
    edit = seeded.case_edit_references[0]
    service.save_case_drafts(scope, updated_generation, [CaseDraftUpdate(binding=seeded.case_bindings[0],
        baseline_interface_id=1, expected_draft_revision=edit.draft_revision,
        expected_publication_revision=edit.publication_revision)])
    receipt = service.publish(scope, "cases", PublicationRequest(request_id="request-updated-case", scope="all"))
    assert receipt.results[0].status == "PUBLISHED"
    assert service.get_case(scope, "case-public").impact_status == "CURRENT"

    # 后续共享指针变化只影响下一次新修订，不能悄悄改写这个已经启动的任务引用。
    database.execute("UPDATE ot_baseline_interface SET current_contract_revision=1 WHERE baseline_interface_id=2")
    _, reference, fixed_contract = engine._visible_dependency_knowledge(seeded, capabilities["scan-2"])
    assert reference.contract_revision == 2 and fixed_contract.contract_revision == 2
