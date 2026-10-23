"""验证任务内下游接口发现只消费固定扫描与明确的本地依赖。"""

from pathlib import Path
import zipfile

import pytest

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.operation_contract_store import OperationContractStore
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.downstream_interfaces import DownstreamInterfaceSearchService
from opentest.domain.case_template_v4 import CaseTemplateSourceScope
from opentest.domain.errors import KnowledgeValidationError, ScopeViolationError
from opentest.domain.models import DsfOperationDefinition, ScanManifest, SourceReference, SystemDefinition
from opentest.domain.system_relations import DownstreamOperationResolveRequest


@pytest.mark.parametrize("candidate_count,gaps,expected", [
    (0, ["固定POM的本地依赖缺失"], "固定POM的本地依赖缺失"),
    (0, [], "核对当前固定依赖"),
    (2, ["其他模块缺少sources.jar"], "存在重载"),
])
def test_resolution_distinguishes_missing_materials_from_overloads(tmp_path, monkeypatch, candidate_count, gaps, expected):
    """依赖解析按候选数量报告可处理原因，不让缺失材料误导Agent去猜签名。

    Args:
        tmp_path: 隔离源码和元数据目录。
        monkeypatch: 替换本地依赖索引，防止查询真实Maven或业务服务。
        candidate_count: 当前精确方法的候选数量。
        gaps: 依赖检索器已发现的材料缺口。
        expected: 应向调用者展示的原因片段。
    """

    service, scope, _ = _search_fixture(tmp_path)
    candidate = {"interface_name": "demo.api.TradeFacade", "method_name": "query", "signature": "query(String)"}
    # 只隔离依赖检索；真实resolve仍执行任务固定来源及操作选择校验。
    monkeypatch.setattr(service, "_maven_interfaces", lambda *args: ([candidate] * candidate_count, gaps))
    with pytest.raises(KnowledgeValidationError, match=expected) as failure:
        service.resolve("caller", [scope], DownstreamOperationResolveRequest(
            downstream_system="remote", interface_name="demo.api.TradeFacade", method_name="query"))
    if not candidate_count:
        assert "demo.api.TradeFacade#query" in str(failure.value)
        assert "重载" not in str(failure.value)


def _search_fixture(tmp_path: Path) -> tuple[DownstreamInterfaceSearchService, CaseTemplateSourceScope, Path]:
    """创建带精确POM依赖和下游XML引用的任务固定源码。

    Args:
        tmp_path: 测试隔离目录。
    Returns:
        只读检索服务、任务源码范围和可写入测试JAR的精确版本目录。
    """

    source = tmp_path / "caller"
    source.mkdir()
    (source / "pom.xml").write_text('''<project xmlns="http://maven.apache.org/POM/4.0.0">
<groupId>demo</groupId><artifactId>caller</artifactId><version>1</version>
<properties><provider.version>2.1</provider.version></properties>
<dependencyManagement><dependencies><dependency><groupId>demo</groupId><artifactId>provider-api</artifactId><version>${provider.version}</version></dependency></dependencies></dependencyManagement>
<dependencies><dependency><groupId>demo</groupId><artifactId>provider-api</artifactId></dependency></dependencies>
</project>''')
    store = GitKnowledgeStore(tmp_path / "knowledge")
    store.register_system(SystemDefinition(system_id="caller", name="caller", source_path=str(source)))
    baseline = GitSourceRepository().capture(source)
    manifest = ScanManifest(scan_id="scan-caller", system_id="caller", baseline=baseline,
                            dsf_operations=[DsfOperationDefinition(operation_id="dsf:remote:trade:query", provider_system_id="remote",
                            gs_name="dsf.remote", service_name="trade", version="1", action="query",
                            source_refs=[SourceReference(path="rpc.xml", symbol="demo.api.TradeFacade#query", line=1)])])
    artifacts = SourceScanArtifactStore(store.root)
    artifacts.write_manifest(manifest)
    # JAR属于任务POM精确依赖；不需要注册remote，也不允许读取其他版本。
    jar_root = tmp_path / "maven/demo/provider-api/2.1"
    jar_root.mkdir(parents=True)
    scope = CaseTemplateSourceScope(source_system_id="caller", source_scan_id=manifest.scan_id, source_baseline=baseline)
    return DownstreamInterfaceSearchService(store, artifacts, tmp_path / "maven"), scope, jar_root


def test_open_resolution_does_not_replace_closed_response_contract(tmp_path: Path) -> None:
    """最新契约是空响应时仍保留更早的闭合响应，避免固定依赖降级。"""

    service, scope, _ = _search_fixture(tmp_path)
    closed = {"type": "object", "properties": {
        "list": {"type": "object", "properties": {"pageList": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}}}}}},
        "success": {"type": "boolean"},
    }}
    opened = {"type": "object", "properties": {"list": {}}}
    definition = DsfOperationDefinition(
        operation_id="dsf:remote:trade:query", provider_system_id="remote", gs_name="dsf.remote",
        service_name="trade", version="1", action="query", request_type="demo.api.QueryRequest",
        response_type="demo.api.QueryResponse",
        request_schema={"type": "object", "properties": {"page": {"type": "integer"}}},
        response_schema=opened,
        source_refs=[SourceReference(path="rpc.xml", symbol="demo.api.TradeFacade#query", line=1)],
    )
    service._register_resolved("caller", scope.source_scan_id, definition)
    contracts = OperationContractStore(service.store.root / "contracts", service.artifacts.metadata)
    latest = contracts.get_latest("caller", scope.source_scan_id, definition.operation_id)
    contracts.save("caller", latest.model_copy(update={"contract_revision": 1, "response_schema": closed}))
    contracts.save("caller", latest.model_copy(update={"contract_revision": 2, "response_schema": opened}))
    service._register_resolved("caller", scope.source_scan_id, definition)

    latest = contracts.get_latest("caller", scope.source_scan_id, definition.operation_id)
    assert latest.contract_revision == 3
    assert latest.response_schema["properties"]["list"]["properties"]["pageList"]["items"]["properties"]["id"] == {"type": "integer"}


def test_unregistered_source_dependency_exposes_extra_method_without_execution(tmp_path: Path) -> None:
    """未接入系统可从精确sources.jar发现XML之外的方法，并保留DTO结构。

    Args:
        tmp_path: 测试源码和Maven仓库。
    """

    service, scope, jar_root = _search_fixture(tmp_path)
    with zipfile.ZipFile(jar_root / "provider-api-2.1-sources.jar", "w") as archive:
        archive.writestr("demo/api/TradeFacade.java", '''package demo.api;
public interface TradeFacade {
/** 取消指定订单。 */
CancelResponse cancel(CancelRequest request);
String query(String orderNo);
}''')
        archive.writestr("demo/api/CancelRequest.java", "package demo.api;\npublic class CancelRequest {\n private String orderNo;\n}")
        archive.writestr("demo/api/CancelResponse.java", "package demo.api;\npublic class CancelResponse {\n private boolean success;\n}")
    result = service.search("caller", [scope], "dsf.remote", "cancel")

    assert result["total"] == 1
    method = result["interfaces"][0]
    assert method["summary"] == "取消指定订单。"
    assert method["request_types"] == ["demo.api.CancelRequest"]
    assert method["executable"] is False
    assert method["coordinate"] == "demo:provider-api:2.1"
    assert {item["type_name"]: item["fields"] for item in method["dto_types"]}["demo.api.CancelRequest"] == [
        {"name": "orderNo", "type": "java.lang.String", "summary": ""}]
    # 检索不修改调用方白名单，也不把新方法写入静态扫描。
    manifest = service.artifacts.read("caller", scope.source_scan_id)
    assert [operation.action for operation in manifest.dsf_operations] == ["query"]


def test_binary_only_dependency_keeps_missing_documentation_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只有二进制依赖时返回公共签名和DTO字段，不将方法名伪装为业务说明。

    Args:
        tmp_path: 测试依赖目录。
        monkeypatch: 模拟JDK元数据输出，不执行业务类。
    """

    service, scope, jar_root = _search_fixture(tmp_path)
    # 不安装源码包，复现企业Maven依赖通常只有binary JAR的实际形态。
    with zipfile.ZipFile(jar_root / "provider-api-2.1.jar", "w") as archive:
        archive.writestr("demo/api/TradeFacade.class", b"test")
        archive.writestr("demo/api/CancelRequest.class", b"test")

    def metadata(path: Path, class_name: str, private: bool = False) -> str:
        """返回固定公共接口和请求类型的JDK文本，确保未运行依赖字节码。

        Args:
            path: 服务根据POM选定的JAR。
            class_name: 元数据类型名。
            private: DTO字段读取模式。
        Returns:
            与javap实际格式一致的接口或类型声明。
        """

        assert path.name == "provider-api-2.1.jar"
        if class_name == "demo.api.TradeFacade":
            return "public interface demo.api.TradeFacade {\n public abstract boolean cancel(demo.api.CancelRequest);\n}"
        return "public class demo.api.CancelRequest {\n private java.lang.String orderNo;\n private static final long serialVersionUID;\n}"

    monkeypatch.setattr(service, "_javap", metadata)
    result = service.search("caller", [scope], "remote", "cancel")
    assert result["interfaces"][0]["summary"] == ""
    assert result["interfaces"][0]["executable"] is False
    assert result["interfaces"][0]["dto_types"][0]["fields"] == [{"name": "orderNo", "type": "java.lang.String", "summary": ""}]
    assert any("sources.jar" in gap for gap in result["gaps"])


def test_search_rejects_unknown_downstream_and_never_chooses_another_version(tmp_path: Path) -> None:
    """搜索参数不能扩大系统范围，本地另一个版本不能代替固定依赖。

    Args:
        tmp_path: 模拟本机依赖仓库。
    """

    service, scope, jar_root = _search_fixture(tmp_path)
    # 任意系统参数必须在文件搜索前被拒绝，而不是借机枚举本机依赖仓库。
    with pytest.raises(ScopeViolationError, match="not declared"):
        service.search("caller", [scope], "dsf.unrelated")
    # 任务系统自身不是下游；错误需指向自身候选索引与选择工具，Agent才能修正调用而非放弃取数。
    with pytest.raises(ScopeViolationError, match="related_interface_index; select one with read_outer_api_info"):
        service.search("caller", [scope], "caller")
    different = jar_root.parent / "9.0"
    different.mkdir()
    with zipfile.ZipFile(different / "provider-api-9.0-sources.jar", "w") as archive:
        archive.writestr("demo/api/TradeFacade.java", "package demo.api; public interface TradeFacade { String cancel(); }")
    result = service.search("caller", [scope], "remote", "cancel")
    assert result["interfaces"] == []
    assert any("未找到" in gap for gap in result["gaps"])


def test_registered_provider_uses_frozen_scan_for_unreferenced_methods(tmp_path: Path) -> None:
    """已接入下游可寻找调用方未引用的方法，但不追随任务启动后的latest。

    Args:
        tmp_path: 隔离任务、提供方源码及扫描目录。
    """

    service, caller_scope, _ = _search_fixture(tmp_path)
    # 提供方固定扫描包含caller XML之外的发布，发现它不要求先创建知识条目。
    source = tmp_path / "provider"
    source.mkdir()
    service.store.register_system(SystemDefinition(system_id="provider", name="provider", source_path=str(source)))
    baseline = GitSourceRepository().capture(source)
    operation = DsfOperationDefinition(operation_id="dsf:provider:trade:cancel", provider_system_id="provider",
                                       gs_name="dsf.remote", service_name="trade", version="1", action="cancel",
                                       request_type="demo.api.CancelRequest", response_type="demo.api.CancelResponse",
                                       source_refs=[SourceReference(path="TradeFacade.java", symbol="demo.api.TradeFacade#cancel", line=2)])
    manifest = ScanManifest(scan_id="scan-provider-frozen", system_id="provider", baseline=baseline, dsf_operations=[operation])
    service.artifacts.write_manifest(manifest)
    provider_scope = CaseTemplateSourceScope(source_system_id="provider", source_scan_id=manifest.scan_id, source_baseline=baseline)
    result = service.search("caller", [caller_scope, provider_scope], "remote", "cancel")

    assert result["total"] == 1
    assert result["interfaces"][0]["source_kind"] == "registered_scan"
    assert result["interfaces"][0]["source_scan_id"] == "scan-provider-frozen"
    assert result["interfaces"][0]["method_name"] == "cancel"
    assert result["interfaces"][0]["executable"] is False


@pytest.mark.parametrize('new_service', [False, True])
def test_registered_provider_resolves_without_a_local_dependency_jar(tmp_path: Path, new_service: bool) -> None:
    """已注册提供方契约直接复用；新服务的独立发布版本不受调用方其他版本影响。"""

    from opentest.adapters.operation_contract_store import OperationContractStore
    from opentest.domain.system_relations import DownstreamOperationResolveRequest

    service, caller_scope, _ = _search_fixture(tmp_path)
    if new_service:
        # 调用方已用两个不同版本的服务，也不妨碍解析提供方独立发布的新服务。
        caller = service.artifacts.read('caller', caller_scope.source_scan_id)
        caller.dsf_operations.append(caller.dsf_operations[0].model_copy(update={
            'operation_id': 'dsf:remote:account:query', 'service_name': 'account', 'version': '2'}))
        service.artifacts.write_manifest(caller)
    source = tmp_path / 'provider'
    source.mkdir()
    service.store.register_system(SystemDefinition(system_id='provider', name='provider', source_path=str(source)))
    baseline = GitSourceRepository().capture(source)
    definition = DsfOperationDefinition(operation_id='dsf:provider:trade:cancel', provider_system_id='provider',
        gs_name='dsf.remote', service_name='trade', version='1', action='cancel',
        request_schema={'type': 'object', 'properties': {'orderNo': {'type': 'string'}}},
        response_schema={'type': 'object', 'properties': {'success': {'type': 'boolean'}}},
        source_refs=[SourceReference(path='TradeFacade.java', symbol='demo.api.TradeFacade#cancel', line=2)])
    if new_service:
        definition = definition.model_copy(update={'operation_id': 'dsf:provider:cancel:cancel', 'service_name': 'cancel', 'version': '3'})
    manifest = ScanManifest(scan_id='scan-provider-frozen', system_id='provider', baseline=baseline, dsf_operations=[definition])
    service.artifacts.write_manifest(manifest)
    provider_scope = CaseTemplateSourceScope(source_system_id='provider', source_scan_id=manifest.scan_id, source_baseline=baseline)
    resolved = service.resolve('caller', [caller_scope, provider_scope], DownstreamOperationResolveRequest(
        downstream_system='remote', interface_name='demo.api.TradeFacade', method_name='cancel'))
    assert resolved.request_schema == definition.request_schema
    assert resolved.version == ('3' if new_service else '1')
    registered = OperationContractStore(service.store.root / 'contracts').read_operations('caller', caller_scope.source_scan_id)
    assert registered[definition.operation_id] == resolved
    assert len(service.artifacts.read('caller', caller_scope.source_scan_id).dsf_operations) == (2 if new_service else 1)


def test_partial_keyword_match_still_searches_dependency_and_paginates(tmp_path, monkeypatch):
    """目录命中query后仍需查找缺失的cancel，分页总数包括两种来源且不重复。"""

    from opentest.domain.system_relations import DownstreamInterfaceQuery

    service, scope, _ = _search_fixture(tmp_path)
    manifest = service.artifacts.read('caller', scope.source_scan_id)
    manifest.dsf_operations[0].request_schema = {'type': 'object'}
    manifest.dsf_operations[0].response_schema = {'type': 'object'}
    service.artifacts.write_manifest(manifest)
    calls = []

    def candidates(root, symbols, query):
        """返回固定classpath新增的方法；记录调用证明部分命中没有跳过检索。"""
        calls.append(query)
        candidate = {'interface_name': 'demo.api.TradeFacade', 'method_name': 'cancel', 'signature': 'cancel(Request)'}
        return [candidate, candidate], []

    monkeypatch.setattr(service, '_maven_interfaces', candidates)
    first = service.search_page('caller', [scope], DownstreamInterfaceQuery(downstream_system='remote', query='query cancel', limit=1))
    second = service.search_page('caller', [scope], DownstreamInterfaceQuery(downstream_system='remote', query='query cancel', limit=1, offset=1))
    assert calls == ['query cancel', 'query cancel']
    assert first['total'] == second['total'] == 2
    assert first['next_offset'] == 1 and second['next_offset'] is None
    assert {first['interfaces'][0]['method_name'], second['interfaces'][0]['method_name']} == {'query', 'cancel'}


def test_exact_operation_version_is_independent_of_other_services(tmp_path):
    """同下游其他服务使用不同版本时，精确命中的完整接口仍能解析登记。"""

    from opentest.domain.system_relations import DownstreamOperationResolveRequest

    service, scope, _ = _search_fixture(tmp_path)
    manifest = service.artifacts.read('caller', scope.source_scan_id)
    query = manifest.dsf_operations[0]
    query.request_schema = {'type': 'object'}
    query.response_schema = {'type': 'object'}
    manifest.dsf_operations.append(query.model_copy(update={
        'operation_id': 'dsf:remote:account:queryAccount', 'service_name': 'account', 'action': 'queryAccount', 'version': '2',
        'source_refs': [SourceReference(path='rpc.xml', symbol='demo.api.AccountFacade#queryAccount', line=2)]}))
    service.artifacts.write_manifest(manifest)
    resolved = service.resolve('caller', [scope], DownstreamOperationResolveRequest(
        downstream_system='remote', interface_name='demo.api.TradeFacade', method_name='query'))
    assert resolved.version == '1' and resolved.service_name == 'trade'
