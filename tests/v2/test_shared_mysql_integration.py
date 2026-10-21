"""显式启用的真实MySQL隔离库验收；只创建并清理随机测试库，绝不修改配置中的业务库。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import yaml

from opentest.adapters.mysql_knowledge import MySqlKnowledgeStore
from opentest.adapters.mysql_metadata import MySqlMetadataStore, decode_json, encode_json, pack_json
from opentest.adapters.shared_history_migration import SharedHistoryMigration
from opentest.adapters.shared_schema_upgrade import ADDED_COLUMNS, ADDED_INDEXES, NEW_TABLES, SharedSchemaUpgrade
from opentest.adapters.shared_workspace_store import SharedWorkspaceStore
from opentest.application.publication import PublicationService
from opentest.application.shared_baselines import SharedBaselineService
from opentest.application.shared_interface_knowledge import SharedInterfaceKnowledgeService
from opentest.domain.case_template_v4 import CaseTemplateGenerationV4
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import KnowledgeContextProfile, KnowledgeNode, OperationInputKnowledgeContract, ScanManifest, SourceBaseline
from opentest.domain.publication import PublicationRequest, PublicationScope
from opentest.domain.shared_workspace import BaselineCreationRun, CreateCodeBaseline, InterfaceKnowledgeBundle


@pytest.fixture
def isolated_mysql(tmp_path):
    """读取明确指定配置但连接随机测试库；finally只删除本次已成功创建的专用库。"""

    config_path = os.environ.get("OPENTEST_SHARED_MYSQL_TEST_CONFIG")
    if not config_path:
        pytest.skip("未显式启用隔离MySQL集成测试")
    import pymysql

    configuration = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    database = f"opentest_shared_test_{uuid.uuid4().hex[:12]}"
    password = os.environ[configuration["password_env"]] if configuration.get("password_env") else configuration.get("password", "")
    # 不传原database，创建和清理仅使用本函数生成、校验过的专用数据库身份。
    administrative = pymysql.connect(host=configuration["host"], port=int(configuration.get("port", 3306)),
        user=configuration["user"], password=password, charset="utf8mb4", autocommit=True, connect_timeout=10)
    created = False
    first = second = None
    try:
        with administrative.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        created = True
        test_configuration = {**configuration, "database": database}
        first = MySqlMetadataStore(test_configuration, "test-workspace-a")
        second = MySqlMetadataStore(test_configuration, "test-workspace-b")
        first.install_schema()
        yield first, second, tmp_path
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        if created:
            assert database.startswith("opentest_shared_test_") and database != configuration["database"]
            with administrative.cursor() as cursor:
                cursor.execute(f"DROP DATABASE `{database}`")
        administrative.close()


def _contract(scan_id: str) -> OperationInputKnowledgeContract:
    """返回带真实范围引用的最小空入参契约，用于历史和新员工发布验证。"""

    return OperationInputKnowledgeContract(contract_version="operation-contract/v2", contract_revision=1,
        target_id="query-order", source_scan_id=scan_id, source_commit="a" * 40, status="READY",
        request_schema={"type": "object", "properties": {}}, operation_summary="查询订单")


def _generation(digit: str, scan_id: str, predecessor: str = "") -> CaseTemplateGenerationV4:
    """构造可执行固定Generation；不同实例可表达同基准替代链和跨基准独立集合。"""

    evidence = {"source_system_id": "orders", "path": "Order.java"}
    oracle = {"oracle_id": "oracle-ok", "channel": "response", "assertions": [{"actual_path": "id", "operator": "exists"}]}
    template = {"template_id": "query-order", "title": "订单查询", "coverage_kind": "business", "parameters": [],
        "request_bindings": [{"field": "page", "source": {"kind": "literal", "value": 1}}],
        "combination": "each", "oracles": [oracle], "evidence": [evidence]}
    return CaseTemplateGenerationV4.model_validate({"generation_id": "case-template-generation-" + digit * 20,
        "predecessor_generation_id": predecessor, "system_id": "orders", "operation_id": "query-order",
        "source_scan_id": scan_id, "coverage_id": "coverage-query", "runtime_registry_version": "runtime-functions/v1",
        "value_registry_version": "value-functions/v1", "status": "READY", "input_contract": _contract(scan_id).model_dump(),
        "submission": {"data_functions": [], "case_templates": [template], "unresolved": []},
        "variants": [{"variant_id": "case-variant-v4-" + digit * 20, "template_id": "query-order", "ordinal": 1,
            "parameter_values": {}, "request_values": {}, "data_calls": [], "oracles": [oracle]}]})


def _seed_history(metadata: MySqlMetadataStore) -> list[str]:
    """写入隔离库中的旧共享扫描、当前背景及独立Case集；返回应保留Generation身份。"""

    context = KnowledgeContextProfile(system_id="orders", system_purpose="原系统订单背景")
    metadata.execute("INSERT INTO ot_system(system_id,system_json,context_json,latest_scan_id) VALUES('orders','{}',%s,'scan-one')", (context.model_dump_json(),))
    for scan_id, digit in (("scan-one", "a"), ("scan-two", "b")):
        metadata.execute("INSERT INTO ot_scan(scan_id,system_id,source_commit,selected_revision,baseline_json,summary_json,manifest_gzip) VALUES(%s,'orders',%s,'main',%s,'{}',%s)",
            (scan_id, digit * 40, encode_json({"commit": digit * 40, "dirty": False}), pack_json({})))
        metadata.execute("INSERT INTO ot_interface(system_id,scan_id,operation_id,definition_json,latest_contract_revision) VALUES('orders',%s,'query-order','{}',1)", (scan_id,))
        interface = metadata.fetch_one("SELECT interface_id FROM ot_interface WHERE scan_id=%s", (scan_id,))
        contract = _contract(scan_id).model_copy(update={"source_commit": digit * 40})
        node = KnowledgeNode(node_id=f"node-{scan_id}", system_id="orders", kind="facade", title="订单查询", aliases=["query-order"], input_contract=contract)
        bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={node.node_id: "原始固定知识正文"}, context=context)
        metadata.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,knowledge_json) VALUES(%s,1,%s,%s)",
            (interface["interface_id"], contract.model_dump_json(), bundle.model_dump_json()))
    first = _generation("a", "scan-one")
    replacement = _generation("b", "scan-one", first.generation_id)
    independent = _generation("c", "scan-one")
    different_baseline = _generation("d", "scan-two", replacement.generation_id)
    for generation in (first, replacement, independent, different_baseline):
        metadata.execute("INSERT INTO ot_case_generation(generation_id,system_id,operation_id,source_scan_id,status,generation_json) VALUES(%s,'orders','query-order',%s,'READY',%s)",
            (generation.generation_id, generation.source_scan_id, generation.model_dump_json()))
    return [replacement.generation_id, independent.generation_id, different_baseline.generation_id]


def test_real_schema_explicit_upgrade_and_history_migration_are_repeatable(isolated_mysql):
    """真实DDL验证7+5升级和重放；历史替代链仅在同基准生效，未声明默认字段不被写回。"""

    metadata, other_workspace, root = isolated_mysql
    # 仅把已创建的随机空测试库还原到旧结构，以覆盖真实ALTER而不是仅检查SQL文本。
    for table, index in ADDED_INDEXES.items():
        metadata.execute(f"ALTER TABLE {table} DROP INDEX {index}")
    for table, columns in ADDED_COLUMNS.items():
        for column in columns:
            metadata.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    for table in NEW_TABLES:
        metadata.execute(f"DROP TABLE {table}")
    upgrade = SharedSchemaUpgrade(metadata)
    assert len(upgrade.plan()) == 23
    assert len(upgrade.plan()) == 23
    upgrade.apply()
    assert upgrade.plan() == []
    expected = _seed_history(metadata)
    # 历史JSON允许省略默认字段；迁移须保留原表达，而不是借模型序列化顺手扩写业务契约。
    original_row = metadata.fetch_one("SELECT generation_json FROM ot_case_generation WHERE generation_id=%s", (expected[0],))
    original_payload = decode_json(original_row["generation_json"])
    original_payload["input_contract"].pop("fields")
    original_payload["submission"].pop("semantic_draft")
    original_payload["variants"][0].pop("blocked_reason")
    CaseTemplateGenerationV4.model_validate(original_payload)
    metadata.execute("UPDATE ot_case_generation SET generation_json=%s WHERE generation_id=%s", (encode_json(original_payload), expected[0]))
    existing = SharedWorkspaceStore(metadata).create_baseline(CreateCodeBaseline(system_id="orders", source_commit="a" * 40,
        selected_revision="already-created", user_id="employee-a"))
    metadata.execute("INSERT INTO ot_baseline_interface(baseline_id,operation_id,availability) VALUES(%s,'query-order','UNPUBLISHED')", (existing.baseline_id,))
    migration = SharedHistoryMigration(metadata)
    before = migration.plan()
    assert set(before.current_generations) == set(expected)
    assert metadata.fetch_one("SELECT COUNT(*) AS amount FROM ot_code_baseline")["amount"] == 1
    migration.apply()
    rows = other_workspace.fetch_all("SELECT baseline_id,context_json,created_by_user_id,source_artifact_id FROM ot_code_baseline")
    assert len(rows) == 2 and all(row["source_artifact_id"] is None for row in rows)
    assert next(row for row in rows if row["baseline_id"] == existing.baseline_id)["created_by_user_id"] == "employee-a"
    assert all("原系统订单背景" in row["context_json"] for row in rows)
    first_cases = metadata.fetch_all("SELECT case_id,current_generation_id FROM ot_case ORDER BY case_id")
    assert {row["current_generation_id"] for row in first_cases} == set(expected)
    migration.apply()
    assert metadata.fetch_all("SELECT case_id,current_generation_id FROM ot_case ORDER BY case_id") == first_cases
    migrated_row = metadata.fetch_one("SELECT generation_json FROM ot_case_generation WHERE generation_id=%s", (expected[0],))
    migrated_payload = decode_json(migrated_row["generation_json"])
    assert migrated_payload["input_contract"] == original_payload["input_contract"]
    assert migrated_payload["submission"] == original_payload["submission"]
    assert migrated_payload["variants"] == original_payload["variants"]
    shared = SharedWorkspaceStore(other_workspace).list_baselines("orders", "employee-b")
    assert len(shared) == 2
    service = PublicationService(MySqlKnowledgeStore(root / "other", other_workspace))
    assert service.list_interfaces(PublicationScope(system_id="orders", baseline_id=existing.baseline_id, user_id="employee-b"))


def test_real_migration_allows_explicit_unavailable_without_touching_original(isolated_mysql):
    """损坏历史记录阻止默认切换；明确隔离后保留原载荷，其他正常共享成果可迁移。"""

    metadata, _, _ = isolated_mysql
    _seed_history(metadata)
    metadata.execute("INSERT INTO ot_case_generation(generation_id,system_id,operation_id,source_scan_id,status,generation_json) VALUES('broken-old','orders','query-order','scan-missing','BLOCKED','{}')")
    migration = SharedHistoryMigration(metadata)
    with pytest.raises(KnowledgeValidationError, match="未处理历史异常"):
        migration.apply()
    with pytest.raises(KnowledgeValidationError, match="确认人"):
        migration.apply({"broken-old"})
    migration.apply({"broken-old"}, confirmed_by="employee-a")
    assert metadata.fetch_one("SELECT generation_json FROM ot_case_generation WHERE generation_id='broken-old'")["generation_json"] == "{}"
    decision = metadata.get_workflow("baseline_migration_issue", "broken-old")
    assert decision["disposition"] == "UNAVAILABLE" and decision["confirmed_by"] == "employee-a" and decision["confirmed_at"]
    assert decision["affected_actions"]
    assert all(issue.disposition != "UNRESOLVED" for issue in migration.plan().issues)
    migration.apply()
    assert metadata.get_workflow("baseline_migration_issue", "broken-old") == decision


def test_real_two_workspaces_keep_private_interface_until_explicit_publication(isolated_mysql):
    """两台真实连接各自查询，同员工草稿可复用，另一员工只在显式发布后看到内容。"""

    metadata, other_workspace, root = isolated_mysql
    _seed_history(metadata)
    SharedHistoryMigration(metadata).apply()
    baseline = metadata.fetch_one("SELECT baseline_id FROM ot_scan WHERE scan_id='scan-one'")["baseline_id"]
    interface = metadata.fetch_one("SELECT interface_id FROM ot_interface WHERE scan_id='scan-one'")["interface_id"]
    stable = metadata.fetch_one("SELECT baseline_interface_id FROM ot_baseline_interface WHERE baseline_id=%s", (baseline,))["baseline_interface_id"]
    contract = _contract("scan-one").model_copy(update={"contract_revision": 2, "operation_summary": "员工A的私有修改"})
    node = KnowledgeNode(node_id="private-node", system_id="orders", kind="facade", title="私有修改")
    bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={node.node_id: "员工A的私有知识"})
    metadata.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,knowledge_json,author_user_id) VALUES(%s,2,%s,%s,'employee-a')",
        (interface, contract.model_dump_json(), bundle.model_dump_json()))
    metadata.execute("INSERT INTO ot_interface_draft(baseline_interface_id,owner_user_id,interface_id,contract_revision,change_kind,expected_publication_revision,draft_revision,status) VALUES(%s,'employee-a',%s,2,'UPSERT',1,1,'READY')", (stable, interface))
    service_a = PublicationService(MySqlKnowledgeStore(root / "first", metadata))
    service_b = PublicationService(MySqlKnowledgeStore(root / "second", other_workspace))
    scope_a = PublicationScope(system_id="orders", baseline_id=baseline, user_id="employee-a")
    scope_b = scope_a.model_copy(update={"user_id": "employee-b"})
    assert service_b.list_interfaces(scope_b, "mine") == []
    assert service_b.list_interfaces(scope_a, "mine")[0]["contract"]["operation_summary"] == "员工A的私有修改"
    assert service_b.list_interfaces(scope_b)[0]["contract"]["operation_summary"] == "查询订单"
    service_a.publish(scope_a, "interfaces", PublicationRequest(request_id="publish-real-test-1", scope="all"))
    assert service_b.list_interfaces(scope_b)[0]["contract"]["operation_summary"] == "员工A的私有修改"


def test_real_knowledge_generation_creates_only_owner_draft_and_progress_survives_reload(isolated_mysql):
    """实际知识服务保存完整bundle及草稿，旧共享指针不变；刷新只恢复本人员工最近创建尝试。"""

    metadata, other_workspace, root = isolated_mysql
    _seed_history(metadata)
    SharedHistoryMigration(metadata).apply()
    baseline_id = metadata.fetch_one("SELECT baseline_id FROM ot_scan WHERE scan_id='scan-one'")["baseline_id"]
    manifest = ScanManifest(scan_id="new-private-scan", system_id="orders", baseline=SourceBaseline(source_path="", commit="a" * 40))
    contract = _contract(manifest.scan_id).model_copy(update={"contract_revision": 0, "operation_summary": "新扫描固定契约"})
    metadata.execute("INSERT INTO ot_scan(scan_id,system_id,source_commit,selected_revision,baseline_json,summary_json,manifest_gzip,baseline_id,created_by_user_id) VALUES(%s,'orders',%s,'main',%s,'{}',%s,%s,'employee-a')",
        (manifest.scan_id, "a" * 40, manifest.baseline.model_dump_json(), pack_json(manifest.model_dump(mode="json")), baseline_id))
    definition = {"operation": {"business_name": "订单查询", "source_symbol_refs": [{"path": "OrderFacade.java", "commit": "a" * 40}]}}
    metadata.execute("INSERT INTO ot_interface(system_id,scan_id,operation_id,definition_json,latest_contract_revision) VALUES('orders',%s,'query-order',%s,0)",
        (manifest.scan_id, encode_json(definition)))
    interface_id = metadata.fetch_one("SELECT interface_id FROM ot_interface WHERE scan_id=%s", (manifest.scan_id,))["interface_id"]
    metadata.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,author_user_id) VALUES(%s,0,%s,'employee-a')",
        (interface_id, contract.model_dump_json()))
    knowledge_store = MySqlKnowledgeStore(root / "first", metadata)
    service = SharedInterfaceKnowledgeService(knowledge_store, None)
    scope = PublicationScope(system_id="orders", baseline_id=baseline_id, user_id="employee-a")
    frozen = service.freeze_targets(scope)
    draft = service.generate_interface(scope, manifest, "query-order", frozen["query-order"])
    assert draft["status"] == "READY"
    publications = PublicationService(MySqlKnowledgeStore(root / "second", other_workspace))
    assert publications.list_interfaces(scope, "mine")[0]["knowledge"]["bodies"]
    assert publications.list_interfaces(scope)[0]["contract"]["operation_summary"] == "查询订单"
    assert metadata.fetch_one("SELECT latest_scan_id FROM ot_system WHERE system_id='orders'")["latest_scan_id"] == "scan-one"
    assert metadata.fetch_one("SELECT COUNT(*) AS amount FROM ot_knowledge_node")["amount"] == 0
    # 读取另一个工作台的原始持久进度，不依赖浏览器内存或启动进程尚在运行。
    run = BaselineCreationRun(run_id="baseline-run-private", request_id="request-private", system_id="orders", baseline_id=baseline_id,
        owner_user_id="employee-a", environment_id="uat", source_commit="a" * 40, scan_id=manifest.scan_id, status="RUNNING", task_id="task-interrupted")
    metadata.put_workflow("baseline_creation", run.run_id, run.model_dump(mode="json"))
    metadata.put_workflow("task", run.task_id, {"system_id": "orders", "status": "interrupted", "owner_user_id": "employee-a"})
    baseline_service = object.__new__(SharedBaselineService)
    baseline_service.metadata = other_workspace
    baseline_service.store = SharedWorkspaceStore(other_workspace)
    mine = baseline_service.list_with_progress("orders", "employee-a")
    theirs = baseline_service.list_with_progress("orders", "employee-b")
    assert next(item for item in mine if item["baseline_id"] == baseline_id)["last_creation"]["status"] == "INTERRUPTED"
    assert all(item["last_creation"] is None for item in theirs)
