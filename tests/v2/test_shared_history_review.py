"""离线验证历史独立契约准入及同提交扫描并集，执行真实迁移SQL但不连接公司数据库。"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from opentest.adapters.shared_history_migration import SharedHistoryMigration
from opentest.application.publication import PublicationService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import KnowledgeNode, SourceReference
from opentest.domain.publication import PublicationScope
from opentest.domain.shared_workspace import CaseItemBinding, InterfaceKnowledgeBundle, InterfaceKnowledgeRef
from tests.v2.test_shared_mysql_integration import _contract, _generation
from tests.v2.test_shared_publication import KnowledgeTransactions, PublicationDatabase


class HistoryDatabase(PublicationDatabase):
    """扩展已有SQLite事务夹具，用实际SQL覆盖迁移后的单Case可见性和可执行性。"""

    def __init__(self):
        """加入迁移所需列和旧知识表；测试数据完全留在独立内存数据库。"""

        super().__init__()
        self.connection.executescript("""
        ALTER TABLE ot_interface ADD COLUMN latest_contract_revision INTEGER DEFAULT 1;
        CREATE TABLE ot_knowledge_node(system_id TEXT,node_json TEXT,body TEXT);
        INSERT INTO ot_system(system_id) VALUES('orders');
        INSERT INTO ot_code_baseline(baseline_id,system_id,source_kind) VALUES('baseline-one','orders','LEGACY');
        """)
        # SQLite的JSON函数足以表达相同别名成员判断，保持迁移谓词实际执行。
        self.connection.create_function("JSON_QUOTE", 1, json.dumps)
        self.connection.create_function("JSON_CONTAINS", 3, self._json_contains)

    def _json_contains(self, document, candidate, path):
        """实现测试用MySQL JSON数组包含语义；仅支持迁移实际使用的aliases路径。"""

        assert path == "$.aliases"
        return json.loads(candidate) in json.loads(document).get("aliases", [])


def seed_history_interface(database, scan_id, identity, body_kind):
    """写入指定扫描的固定契约与可选旧正文，返回原接口ID；占位正文只用于验证旧标记不构成门禁。"""

    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES(%s,'baseline-one','orders')", (scan_id,))
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(%s,'orders',%s,'query-order')", (identity, scan_id))
    contract = _contract(scan_id).model_copy(update={"summary_evidence_refs": [SourceReference(path="Order.java")]})
    node = KnowledgeNode(node_id=f"node-{scan_id}", system_id="orders", kind="facade", title="订单查询",
        aliases=["query-order"], input_contract=contract)
    # 模拟旧迁移曾保存的占位材料，现有内容与标记须原样保留，但不能代替契约判定。
    if body_kind == "placeholder":
        node = node.model_copy(update={"metadata": {"migration_requires_review": True}})
    bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={node.node_id: "原扫描保存的实现知识正文"})
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,knowledge_json) VALUES(%s,1,%s,%s)",
        (identity, contract.model_dump_json(), bundle.model_dump_json() if body_kind in {"bundle", "placeholder"} else None))
    if body_kind == "legacy":
        database.execute("INSERT INTO ot_knowledge_node VALUES('orders',%s,%s)", (node.model_dump_json(), bundle.bodies[node.node_id]))
    return identity


def migrate_case(database, source_scan, generation=None):
    """迁移指定或默认的严格Generation并返回发布Case；执行实际状态与依赖SQL，不连接外部数据库。"""

    # Generation保留原扫描归属，由生产迁移代码完成稳定接口与影响状态映射。
    generation = generation or _generation("a", source_scan)
    database.execute("INSERT INTO ot_case_generation(generation_id,system_id,generation_json) VALUES(%s,'orders',%s)",
        (generation.generation_id, generation.model_dump_json()))
    migration = SharedHistoryMigration(database)
    migration._migrate_generation(generation.generation_id, {source_scan: "baseline-one"})
    return database.fetch_one("SELECT * FROM ot_case")


@pytest.mark.parametrize("body_kind", ["missing", "legacy", "bundle", "placeholder"])
def test_history_ready_contract_does_not_require_legacy_body(body_kind):
    """独立契约有效即可迁入新Case；缺正文或旧迁移标记不阻塞，也不补造长文。"""

    database = HistoryDatabase()
    identity = seed_history_interface(database, "scan-one", 1, body_kind)
    migration = SharedHistoryMigration(database)
    # 按真实迁移顺序先回填接口再迁Case；重复读取不得补造正文或依赖旧迁移标记。
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    case = migrate_case(database, "scan-one")
    assert case["impact_status"] == "CURRENT"
    stable = database.fetch_one("SELECT baseline_interface_id FROM ot_baseline_interface")
    assert migration._backfill_contract_bundle(stable["baseline_interface_id"], identity, 1, "baseline-one") is True
    if body_kind == "missing":
        assert database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version")["knowledge_json"] is None
    if body_kind == "placeholder":
        assert "migration_requires_review" in database.fetch_one("SELECT knowledge_json FROM ot_interface_contract_version")["knowledge_json"]
    service = PublicationService(KnowledgeTransactions(database))
    assert service.require_executable(PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-b"), case["case_id"], "published").case_id == case["case_id"]


@pytest.mark.parametrize("removed", [False, True])
def test_narrow_same_commit_scan_preserves_valid_case_and_explicit_removal(removed):
    """同提交首选扫描缺项不制造Case变化；固定契约可执行，但显式发布移除仍保持禁用。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-wide", 1, "bundle")
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES('scan-narrow','baseline-one','orders')")
    # 显式发布移除优先于同提交扫描并集，不能被历史补齐重新启用。
    if removed:
        database.execute("INSERT INTO ot_baseline_interface(baseline_id,operation_id,publication_revision,availability) VALUES('baseline-one','query-order',2,'REMOVED')")
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-wide", "scan-narrow"], "scan-narrow")
    interface = database.fetch_one("SELECT * FROM ot_baseline_interface")
    assert interface["availability"] == ("REMOVED" if removed else "AVAILABLE")
    case = migrate_case(database, "scan-wide")
    assert case["impact_status"] == ("INTERFACE_REMOVED" if removed else "CURRENT")
    service = PublicationService(KnowledgeTransactions(database))
    scope = PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-b")
    assert service.list_cases(scope)[0].case_id == case["case_id"]
    if removed:
        with pytest.raises(KnowledgeValidationError):
            service.require_executable(scope, case["case_id"], "published")
    else:
        assert case["impact_details_json"] is None
        assert service.require_executable(scope, case["case_id"], "published").case_id == case["case_id"]


def test_same_commit_union_keeps_ready_contract_without_history_body():
    """同提交宽扫描中的独立契约足以保留历史Case，不要求从未保存过的长文。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-wide", 1, "missing")
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES('scan-narrow','baseline-one','orders')")
    # 并集仅保留同一旧接口及契约指针；没有把较新扫描或长文当成原Case的依据。
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-wide", "scan-narrow"], "scan-narrow")
    case = migrate_case(database, "scan-wide")
    assert case["impact_status"] == "CURRENT"
    assert case["impact_details_json"] is None
    service = PublicationService(KnowledgeTransactions(database))
    assert service.require_executable(PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-b"),
        case["case_id"], "published").case_id == case["case_id"]


@pytest.mark.parametrize("change", [{"target_id": "other-operation"}, {"source_scan_id": "other-scan"},
    {"status": "BLOCKED", "blocked_reason": "字段结构冲突"}])
def test_history_invalid_fixed_contract_still_requires_review(change):
    """缺正文不阻塞，但契约受阻或目标/扫描身份错配仍不能把新Case标为可执行。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-one", 1, "missing")
    changed = _contract("scan-one").model_copy(update=change)
    database.execute("UPDATE ot_interface_contract_version SET contract_json=%s", (changed.model_dump_json(),))
    # 使用实际发布指针和固定版本，避免只检查标签而忽略保存内容的身份错误。
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    case = migrate_case(database, "scan-one")
    assert case["impact_status"] == "NEEDS_UPDATE"


def test_history_embedded_input_contract_must_match_fixed_version():
    """版本号相同但Generation嵌入的请求Schema不同，仍必须复核而不能由READY标签放行。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-one", 1, "missing")
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    generation = _generation("a", "scan-one")
    changed = generation.input_contract.model_copy(update={"request_schema": {"type": "object", "properties": {"different": {"type": "string"}}}})
    case = migrate_case(database, "scan-one", generation.model_copy(update={"input_contract": changed}))
    assert case["impact_status"] == "NEEDS_UPDATE"


@pytest.mark.parametrize("dependency_changed", [False, True])
def test_history_preserves_and_checks_every_fixed_case_dependency(dependency_changed):
    """已有Case绑定中的依赖不被替换成目标单项；任何依赖修订改变都保持需复核。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-one", 1, "missing")
    dependency_contract = _contract("scan-one").model_copy(update={"target_id": "lookup-order"})
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(2,'orders','scan-one','lookup-order')")
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json) VALUES(2,1,%s)", (dependency_contract.model_dump_json(),))
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    references = [InterfaceKnowledgeRef(baseline_interface_id=row["baseline_interface_id"], interface_id=row["current_interface_id"], contract_revision=1)
        for row in database.fetch_all("SELECT * FROM ot_baseline_interface ORDER BY current_interface_id")]
    generation = _generation("a", "scan-one")
    binding = CaseItemBinding(case_id="case-history", variant_id=generation.variants[0].variant_id, knowledge_dependencies=references)
    # 不改原冻结引用，只模拟当前发布指针推进；同commit不能豁免不同实际依赖。
    if dependency_changed:
        database.execute("UPDATE ot_baseline_interface SET current_contract_revision=2 WHERE operation_id='lookup-order'")
    case = migrate_case(database, "scan-one", generation.model_copy(update={"case_bindings": [binding]}))
    assert case["impact_status"] == ("NEEDS_UPDATE" if dependency_changed else "CURRENT")
    assert json.loads(case["knowledge_dependencies_json"]) == [reference.model_dump(mode="json") for reference in references]


def test_history_replay_does_not_clear_existing_review_status():
    """新的迁移准入不自动解除旧Case复核；保留原原因，等待显式发布校验。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-one", 1, "missing")
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    case = migrate_case(database, "scan-one")
    original_details = json.dumps({"reason_code": "MIGRATED_KNOWLEDGE_REVIEW", "message": "原复核结论"})
    database.execute("UPDATE ot_case SET impact_status='NEEDS_UPDATE',impact_details_json=%s", (original_details,))
    # 重放沿用已存在的稳定Case身份，不能借新准入覆盖先前持久状态。
    migration._migrate_generation(case["current_generation_id"], {"scan-one": "baseline-one"})
    replayed = database.fetch_one("SELECT * FROM ot_case")
    assert replayed["impact_status"] == "NEEDS_UPDATE"
    assert replayed["impact_details_json"] == original_details


def test_newer_interface_contract_still_requires_case_update_within_same_commit():
    """同提交扫描并集不覆盖新扫描的知识修订；旧Case固定接口引用不同仍要求更新。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-old", 1, "bundle")
    seed_history_interface(database, "scan-new", 2, "bundle")
    # 同一接口的新知识引用仍优先；本次仅修复首选扫描完全缺项时的误判。
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-old", "scan-new"], "scan-new")
    case = migrate_case(database, "scan-old")
    assert case["impact_status"] == "NEEDS_UPDATE"
    assert json.loads(case["impact_details_json"])["reason_code"] == "MIGRATED_KNOWLEDGE_REVIEW"
    assert database.fetch_one("SELECT current_interface_id FROM ot_baseline_interface")["current_interface_id"] == 2


def test_history_plan_unions_only_same_system_clean_commit():
    """真实分组SQL只合并同系统干净提交，脏扫描、不同commit和其他系统不能借并集认定有效。"""

    database = HistoryDatabase()
    database.connection.executescript("""
        ALTER TABLE ot_system ADD COLUMN latest_scan_id TEXT;
        ALTER TABLE ot_scan ADD COLUMN source_commit TEXT;
        ALTER TABLE ot_scan ADD COLUMN baseline_json TEXT;
        ALTER TABLE ot_scan ADD COLUMN generated_at TEXT;
        ALTER TABLE ot_case_generation ADD COLUMN source_scan_id TEXT;
        ALTER TABLE ot_case_generation ADD COLUMN created_at TEXT;
        INSERT INTO ot_system(system_id,latest_scan_id) VALUES('other','scan-other');
        UPDATE ot_system SET latest_scan_id='scan-narrow' WHERE system_id='orders';
    """)
    database.list_workflows = Mock(return_value=[])
    # 同SHA的脏扫描各自持有不同工作树事实，不能被源码commit相同掩盖。
    scans = [("scan-wide", "orders", "a", False), ("scan-narrow", "orders", "a", False),
        ("scan-dirty-one", "orders", "a", True), ("scan-dirty-two", "orders", "a", True),
        ("scan-different", "orders", "b", False), ("scan-other", "other", "a", False),
        ("scan-unknown-one", "orders", "", False), ("scan-unknown-two", "orders", "", False)]
    for index, (scan_id, system, digit, dirty) in enumerate(scans):
        database.execute("INSERT INTO ot_scan(scan_id,system_id,source_commit,baseline_json,generated_at) VALUES(%s,%s,%s,%s,%s)",
            (scan_id, system, digit * 40, json.dumps({"dirty": dirty}), f"2026-10-22 00:00:0{index}"))
    plan = SharedHistoryMigration(database).plan()
    clean = plan.scan_baselines["scan-wide"]
    assert plan.scan_baselines["scan-narrow"] == clean
    assert plan.baseline_scans[clean] == ["scan-wide", "scan-narrow"]
    assert plan.preferred_scans[clean] == "scan-narrow"
    isolated = [plan.scan_baselines[scan_id] for scan_id in ("scan-dirty-one", "scan-dirty-two", "scan-different",
        "scan-other", "scan-unknown-one", "scan-unknown-two")]
    assert len(set([clean, *isolated])) == 7
