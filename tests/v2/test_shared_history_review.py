"""离线验证历史正文及扫描范围不确定性，执行真实迁移SQL但不连接公司数据库。"""

from __future__ import annotations

import json

import pytest

from opentest.adapters.shared_history_migration import SharedHistoryMigration
from opentest.application.publication import PublicationService
from opentest.domain.errors import KnowledgeValidationError
from opentest.domain.models import KnowledgeNode, SourceReference
from opentest.domain.publication import PublicationScope
from opentest.domain.shared_workspace import InterfaceKnowledgeBundle
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
    """写入指定扫描的固定契约与可选旧正文，返回原接口ID供迁移断言。"""

    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES(%s,'baseline-one','orders')", (scan_id,))
    database.execute("INSERT INTO ot_interface(interface_id,system_id,scan_id,operation_id) VALUES(%s,'orders',%s,'query-order')", (identity, scan_id))
    contract = _contract(scan_id).model_copy(update={"summary_evidence_refs": [SourceReference(path="Order.java")]})
    node = KnowledgeNode(node_id=f"node-{scan_id}", system_id="orders", kind="facade", title="订单查询",
        aliases=["query-order"], input_contract=contract)
    bundle = InterfaceKnowledgeBundle(nodes=[node], bodies={node.node_id: "原扫描保存的实现知识正文"})
    database.execute("INSERT INTO ot_interface_contract_version(interface_id,revision,contract_json,knowledge_json) VALUES(%s,1,%s,%s)",
        (identity, contract.model_dump_json(), bundle.model_dump_json() if body_kind == "bundle" else None))
    if body_kind == "legacy":
        database.execute("INSERT INTO ot_knowledge_node VALUES('orders',%s,%s)", (node.model_dump_json(), bundle.bodies[node.node_id]))
    return identity


def migrate_case(database, source_scan, preferred_scan):
    """迁移一个真实严格Generation并返回发布Case；不以替身绕过状态或依赖计算。"""

    generation = _generation("a", source_scan)
    database.execute("INSERT INTO ot_case_generation(generation_id,system_id,generation_json) VALUES(%s,'orders',%s)",
        (generation.generation_id, generation.model_dump_json()))
    migration = SharedHistoryMigration(database)
    migration._migrate_generation(generation.generation_id, {source_scan: "baseline-one"}, {"baseline-one": preferred_scan})
    return database.fetch_one("SELECT * FROM ot_case")


@pytest.mark.parametrize("body_kind,expected_status", [("missing", "NEEDS_UPDATE"), ("legacy", "CURRENT"), ("bundle", "CURRENT")])
def test_history_contract_placeholder_never_becomes_current_on_replay(body_kind, expected_status):
    """首轮接口回填和Case回填重放均区分原正文与合成声明，后者始终不能执行。"""

    database = HistoryDatabase()
    identity = seed_history_interface(database, "scan-one", 1, body_kind)
    migration = SharedHistoryMigration(database)
    # 接口回填先写入knowledge_json，Case回填随后读取它，覆盖导致误标CURRENT的真实顺序。
    migration._publish_initial_interfaces("baseline-one", ["scan-one"], "scan-one")
    case = migrate_case(database, "scan-one", "scan-one")
    assert case["impact_status"] == expected_status
    stable = database.fetch_one("SELECT baseline_interface_id FROM ot_baseline_interface")
    assert migration._backfill_contract_bundle(stable["baseline_interface_id"], identity, 1, "baseline-one") == (body_kind != "missing")
    if body_kind == "missing":
        assert json.loads(case["impact_details_json"])["reason_code"] == "MIGRATED_KNOWLEDGE_REVIEW"
        service = PublicationService(KnowledgeTransactions(database))
        with pytest.raises(KnowledgeValidationError, match="更新"):
            service.require_executable(PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-b"), case["case_id"], "published")


@pytest.mark.parametrize("removed", [False, True])
def test_narrow_preferred_scan_preserves_interface_but_never_reenables_uncertain_case(removed):
    """首选扫描缺项仍保留旧接口与Case；需复核不可执行，已显式发布移除的接口保持移除。"""

    database = HistoryDatabase()
    seed_history_interface(database, "scan-wide", 1, "bundle")
    database.execute("INSERT INTO ot_scan(scan_id,baseline_id,system_id) VALUES('scan-narrow','baseline-one','orders')")
    if removed:
        database.execute("INSERT INTO ot_baseline_interface(baseline_id,operation_id,publication_revision,availability) VALUES('baseline-one','query-order',2,'REMOVED')")
    migration = SharedHistoryMigration(database)
    migration._publish_initial_interfaces("baseline-one", ["scan-wide", "scan-narrow"], "scan-narrow")
    interface = database.fetch_one("SELECT * FROM ot_baseline_interface")
    assert interface["availability"] == ("REMOVED" if removed else "AVAILABLE")
    case = migrate_case(database, "scan-wide", "scan-narrow")
    assert case["impact_status"] == ("INTERFACE_REMOVED" if removed else "NEEDS_UPDATE")
    if not removed:
        assert json.loads(case["impact_details_json"])["reason_code"] == "MIGRATED_SCAN_SCOPE_REVIEW"
    service = PublicationService(KnowledgeTransactions(database))
    scope = PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-b")
    assert service.list_cases(scope)[0].case_id == case["case_id"]
    with pytest.raises(KnowledgeValidationError):
        service.require_executable(scope, case["case_id"], "published")
