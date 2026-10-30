"""用离线真实SQL事务验证重新生成的完整替换、范围隔离、并发冲突与幂等恢复。"""

from contextlib import nullcontext
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.application.case_template_v4 import CaseTemplateV4Service, CaseTemplateWriteConflictError
from opentest.application.console_queries import ConsoleQueries, TaskListQuery
from opentest.application.foundation import OpenTestApplication
from opentest.application.publication import PublicationService
from opentest.adapters.publication_store import PublicationStore
from opentest.domain.case_template_v4 import CaseTemplateGenerationStartRequest, CaseTemplateGenerationV4
from opentest.domain.errors import IdempotencyConflictError, KnowledgeNotFoundError
from opentest.domain.models import TaskRecord, TaskStatus
from opentest.domain.publication import PublicationScope
from opentest.domain.shared_workspace import CaseSelection
from test_case_template_v4_revision import _handoff
from test_shared_publication import KnowledgeTransactions, PublicationDatabase, generation_payload, seed_interface


@pytest.mark.parametrize("intent", [True, False, None])
def test_task_summary_keeps_only_replacement_intent_from_request(intent):
    """验证列表SQL投影保留原生替换布尔值且不带回整个请求；旧任务没有意图时保持未知。"""

    # 从生产查询取得实际投影，在离线JSON引擎执行；不以预造摘要掩盖遗漏字段。
    metadata = Mock()
    metadata.fetch_one.return_value = {"entries": None}
    queries = ConsoleQueries(SimpleNamespace(store=SimpleNamespace(metadata=metadata)))
    queries.tasks(TaskListQuery(view="summary"))
    sql = metadata.fetch_one.call_args.args[0]
    projection = sql.split(" AS result_summary,", 1)[0].rsplit(" AS effective_status,", 1)[1]
    request = {"operation_id": "query-1", "unrelated_large_input": "do-not-project" * 100}
    if intent is not None:
        request["replace_existing_drafts"] = intent
    payload = json.dumps({"result": {"case_request": request, "body": "private-body"}})
    with sqlite3.connect(":memory:") as connection:
        summary_json = connection.execute(
            f"SELECT {projection} FROM (SELECT ? AS payload_json)", (payload,)).fetchone()[0]
    summary = json.loads(summary_json)
    assert summary["case_request"] == {"replace_existing_drafts": intent}
    assert summary["case_request"]["replace_existing_drafts"] is intent
    assert "do-not-project" not in summary_json and "private-body" not in summary_json


class SqlGenerations:
    """仅适配测试数据库的Generation读写协议；事务与草稿SQL使用生产实现。"""

    def __init__(self, database):
        """绑定离线数据库；不创建额外业务记录或模拟成功回执。"""

        self.database = database

    def get(self, system_id, generation_id):
        """读取精确系统中的不可变产物，返回严格模型；不存在抛领域NotFound。"""

        # 缺失与已提交分别走生产恢复分支，不能一律返回预设候选产物。
        row = self.database.fetch_one("SELECT generation_json FROM ot_case_generation WHERE system_id=%s AND generation_id=%s",
                                      (system_id, generation_id))
        if row is None:
            raise KnowledgeNotFoundError("test generation absent")
        return CaseTemplateGenerationV4.model_validate_json(row["generation_json"])

    def write(self, generation):
        """将严格产物写入同一SQL连接，返回产物；唯一键或存储失败由外层事务处理。"""

        # 不使用内存字典代替Generation，确保失败时确实验证它与草稿一起回滚。
        self.database.execute("INSERT INTO ot_case_generation VALUES(%s,%s,%s,%s,%s)",
            (generation.generation_id, generation.system_id, generation.baseline_id,
             generation.owner_user_id, generation.model_dump_json()))
        return generation


@pytest.fixture
def workspace(tmp_path):
    """建立本次测试独立数据库、接口和编译服务；结束关闭连接，不访问MySQL或业务环境。"""

    # 只替换数据库驱动层，所有替换范围、CAS和草稿写入仍经过生产服务。
    database = PublicationDatabase()
    database.execute("INSERT INTO ot_system(system_id) VALUES('orders')")
    database.execute("INSERT INTO ot_code_baseline(baseline_id,system_id) VALUES('baseline-one','orders')")
    seed_interface(database, 1)
    store = KnowledgeTransactions(database)
    engine = CaseTemplateV4Service.__new__(CaseTemplateV4Service)
    engine.store = store
    engine.generations = SqlGenerations(database)
    original = CaseTemplateGenerationV4.model_validate(generation_payload())
    references = original.case_bindings[0].knowledge_dependencies
    handoff = _handoff(tmp_path).model_copy(update={"system_id": "orders", "entry_id": "query-1",
        "baseline_id": "baseline-one", "owner_user_id": "employee-a", "knowledge_dependencies": references})
    # 新批可以与旧批标题、variant模板相同，删除范围仍必须仅依赖冻结Case身份。
    bindings = [item.model_copy(update={"case_id": f"case-new-{index}"})
                for index, item in enumerate(original.case_bindings)]
    candidate = original.model_copy(update={"generation_id": "case-template-generation-" + "b" * 20,
                                           "case_bindings": bindings})
    scope = PublicationScope(system_id="orders", baseline_id="baseline-one", user_id="employee-a")
    yield SimpleNamespace(database=database, engine=engine, publications=PublicationService(store), scope=scope,
                          original=original, candidate=candidate, handoff=handoff)
    database.connection.close()


def seed_replacement(workspace):
    """保存旧批并冻结完整替换范围，返回携带该范围的handoff；不修改共享指针。"""

    # 与实际启动顺序一致：先有当前草稿，再冻结起点，不能从候选新批推导旧集合。
    workspace.engine._write_or_recover_generation(workspace.original, workspace.handoff)
    frozen = workspace.publications.freeze_case_draft_replacement(workspace.scope, "query-1")
    return workspace.handoff.model_copy(update={"replaced_case_drafts": frozen})


def current_drafts(workspace):
    """通过生产范围查询读取本人当前接口草稿，供事务前后内容直接比较。"""

    return workspace.publications.freeze_case_draft_replacement(workspace.scope, "query-1")


def test_complete_regeneration_replaces_only_current_own_interface_drafts(workspace):
    """完整成功替换READY/INCOMPLETE，保留共享、其他员工/接口/基准/系统和不可变历史。"""

    handoff = seed_replacement(workspace)
    db = workspace.database
    db.execute("UPDATE ot_case_draft SET status='INCOMPLETE' WHERE case_id='case-private'")
    db.execute("UPDATE ot_case SET current_generation_id=%s,current_variant_id=%s,publication_revision=7 WHERE case_id='case-public'",
               (workspace.original.generation_id, workspace.original.variants[0].variant_id))
    db.execute("INSERT INTO ot_case_draft VALUES('case-public','employee-b','other-generation','other-variant',7,2,'READY',NULL)")
    db.execute("INSERT INTO ot_code_baseline(baseline_id,system_id) VALUES('baseline-two','orders'),('baseline-other','other-system')")
    # 同基准另一接口、另一基准和另一系统均放入同员工草稿，避免只验证owner的伪隔离。
    for identity, baseline, operation in [(2, 'baseline-one', 'query-2'), (3, 'baseline-two', 'query-1'), (4, 'baseline-other', 'query-1')]:
        db.execute("INSERT INTO ot_baseline_interface(baseline_interface_id,baseline_id,operation_id) VALUES(%s,%s,%s)",
                   (identity, baseline, operation))
        db.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES(%s,%s)", (f"case-other-{identity}", identity))
        db.execute("INSERT INTO ot_case_draft VALUES(%s,'employee-a','other-generation','other-variant',0,1,'READY',NULL)",
                   (f"case-other-{identity}",))
    db.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES('case-published',1)")
    db.execute("INSERT INTO ot_case_draft VALUES('case-published','employee-a','old-generation','old-variant',0,1,'PUBLISHED',NULL)")
    frozen = current_drafts(workspace)
    handoff = handoff.model_copy(update={"replaced_case_drafts": frozen})
    untouched = db.fetch_all("SELECT * FROM ot_case_draft WHERE owner_user_id='employee-b' OR case_id LIKE 'case-other-%' OR status='PUBLISHED'")
    workspace.engine._write_or_recover_generation(workspace.candidate, handoff)
    assert {item.case_id for item in current_drafts(workspace)} == {"case-new-0", "case-new-1"}
    assert db.fetch_all("SELECT * FROM ot_case_draft WHERE owner_user_id='employee-b' OR case_id LIKE 'case-other-%' OR status='PUBLISHED'") == untouched
    assert db.fetch_one("SELECT publication_revision,current_generation_id FROM ot_case WHERE case_id='case-public'") == {
        "publication_revision": 7, "current_generation_id": workspace.original.generation_id}
    assert workspace.engine.generations.get("orders", workspace.original.generation_id) == workspace.original


@pytest.mark.parametrize("change", ["added", "content", "variant", "draft_revision", "expected_revision", "publication", "status", "published", "discarded"])
def test_concurrent_current_draft_change_rolls_back_new_generation(workspace, change):
    """冻结后集合、内容、状态或任一版本变化都冲突；新Generation和新草稿必须实际回滚。"""

    # 先冻结旧集合，再独立提交另一次用户操作，模拟耗时生成期间发生的真实并发变化。
    handoff = seed_replacement(workspace)
    db = workspace.database
    mutations = {
        "content": "UPDATE ot_case_draft SET generation_id='edited-generation' WHERE case_id='case-public'",
        "variant": "UPDATE ot_case_draft SET variant_id='edited-variant' WHERE case_id='case-public'",
        "draft_revision": "UPDATE ot_case_draft SET draft_revision=2 WHERE case_id='case-public'",
        "expected_revision": "UPDATE ot_case_draft SET expected_publication_revision=2 WHERE case_id='case-public'",
        "publication": "UPDATE ot_case SET publication_revision=2 WHERE case_id='case-public'",
        "status": "UPDATE ot_case_draft SET status='INCOMPLETE' WHERE case_id='case-public'",
        "published": "UPDATE ot_case_draft SET status='PUBLISHED' WHERE case_id='case-public'",
        "discarded": "DELETE FROM ot_case_draft WHERE case_id='case-public'",
    }
    if change == "added":
        db.execute("INSERT INTO ot_case(case_id,baseline_interface_id) VALUES('case-concurrent',1)")
        db.execute("INSERT INTO ot_case_draft VALUES('case-concurrent','employee-a','new-generation','new-variant',0,1,'READY',NULL)")
    else:
        db.execute(mutations[change])
    current = current_drafts(workspace)
    with pytest.raises(IdempotencyConflictError, match="请刷新后重新生成"):
        workspace.engine._write_or_recover_generation(workspace.candidate, handoff)
    assert current_drafts(workspace) == current
    assert db.fetch_one("SELECT case_id FROM ot_case WHERE case_id='case-new-0'") is None
    with pytest.raises(KnowledgeNotFoundError):
        workspace.engine.generations.get("orders", workspace.candidate.generation_id)


@pytest.mark.parametrize("outcome", ["PARTIAL", "BLOCKED", "empty", "blocked_variant", "missing_binding"])
def test_incomplete_regeneration_keeps_old_drafts_without_adding_new_ones(workspace, outcome):
    """不完整产物只能留在任务历史中，不能替换旧批或把可执行部分追加到本人草稿。"""

    # 分别打破状态、非空、可执行及绑定完整性，避免只凭READY字符串接受不完整结果。
    handoff = seed_replacement(workspace)
    candidate = workspace.candidate
    if outcome in {"PARTIAL", "BLOCKED"}:
        candidate = candidate.model_copy(update={"status": outcome})
    elif outcome == "empty":
        candidate = candidate.model_copy(update={"variants": [], "case_bindings": []})
    elif outcome == "blocked_variant":
        blocked = candidate.variants[0].model_copy(update={"blocked_reason": "missing input"})
        candidate = candidate.model_copy(update={"variants": [blocked, candidate.variants[1]]})
    else:
        candidate = candidate.model_copy(update={"case_bindings": candidate.case_bindings[:1]})
    workspace.engine._write_or_recover_generation(candidate, handoff)
    assert current_drafts(workspace) == handoff.replaced_case_drafts
    assert workspace.engine.generations.get("orders", candidate.generation_id) == candidate
    assert workspace.database.fetch_one("SELECT case_id FROM ot_case WHERE case_id='case-new-0'") is None


def test_delete_failure_rolls_back_new_and_old_pointers(workspace, monkeypatch):
    """最后删除阶段失败也回滚新Generation、新Case和旧指针删除，不能仅靠Mock证明原子性。"""

    handoff = seed_replacement(workspace)
    original_delete = PublicationStore.delete_replaced_case_drafts

    def fail_after_delete(store, scope, operation_id, references):
        """先执行真实旧指针删除再抛存储错误，验证整次系统事务会回滚。"""

        # 错误发生在最后阶段，保证此前的新草稿和已删除旧草稿都受事务覆盖。
        original_delete(store, scope, operation_id, references)
        raise RuntimeError("simulated delete storage failure")

    monkeypatch.setattr(PublicationStore, "delete_replaced_case_drafts", fail_after_delete)
    with pytest.raises(RuntimeError, match="delete storage"):
        workspace.engine._write_or_recover_generation(workspace.candidate, handoff)
    assert current_drafts(workspace) == handoff.replaced_case_drafts
    assert workspace.database.fetch_one("SELECT case_id FROM ot_case WHERE case_id='case-new-0'") is None
    with pytest.raises(KnowledgeNotFoundError):
        workspace.engine.generations.get("orders", workspace.candidate.generation_id)


def test_empty_initial_scope_conflicts_after_another_generation_wins(workspace):
    """两个首次生成冻结同一空范围，先完成者正常保存，后完成者必须冲突而不能追加第二批。"""

    # 系统事务会串行提交；按两个请求都已冻结空集合的顺序重放即可检验胜者之后的CAS。
    frozen = current_drafts(workspace)
    assert frozen == []
    handoff = workspace.handoff.model_copy(update={"replaced_case_drafts": frozen})
    workspace.engine._write_or_recover_generation(workspace.original, handoff)
    with pytest.raises(IdempotencyConflictError):
        workspace.engine._write_or_recover_generation(workspace.candidate, handoff)
    assert {item.case_id for item in current_drafts(workspace)} == {"case-public", "case-private"}


def test_committed_generation_recovery_does_not_replace_later_edits(workspace):
    """提交后回执丢失重试复用Generation，不重新检查旧集合或清除随后产生的新编辑。"""

    # 模拟提交成功但上层未收到响应；恢复只能返回旧产物，不能再做一次替换。
    handoff = seed_replacement(workspace)
    persisted = workspace.engine._write_or_recover_generation(workspace.candidate, handoff)
    workspace.database.execute("UPDATE ot_case_draft SET draft_revision=2 WHERE case_id='case-new-0'")
    current = current_drafts(workspace)
    assert workspace.engine._write_or_recover_generation(workspace.candidate, handoff) == persisted
    assert current_drafts(workspace) == current


def test_normal_generation_without_replacement_keeps_append_behavior(workspace):
    """单项和覆盖依赖的普通生成路径仍不删除旧草稿，PARTIAL可执行部分保持现有保存行为。"""

    # 使用原handoff的None意图，不能把无替换意图误当成首次生成的空替换集合。
    seed_replacement(workspace)
    partial = workspace.candidate.model_copy(update={"status": "PARTIAL"})
    workspace.engine._write_or_recover_generation(partial, workspace.handoff)
    assert len(current_drafts(workspace)) == 4


def test_replacement_request_rejects_single_case_revision_and_missing_baseline():
    """整批替换必须有基准且不能夹带单Case修订；默认false保持普通路径。"""

    # 校验入口意图互斥，防止后续冻结时在复用旧身份与分配新身份之间含糊选择。
    selected = CaseSelection(case_id="case-old", generation_id="generation-old", variant_id="variant-old")
    for fields in ({}, {"baseline_id": "baseline-one", "editing_case": selected}):
        with pytest.raises(ValidationError, match="不能同时修订"):
            CaseTemplateGenerationStartRequest(operation_id="query-1", replace_existing_drafts=True, **fields)
    assert not CaseTemplateGenerationStartRequest(operation_id="query-1").replace_existing_drafts


@pytest.mark.parametrize("replace", [False, True])
def test_start_freezes_scope_once_and_preserves_request_identity(workspace, monkeypatch, replace):
    """prepare在首次请求冻结全范围；相同回执恢复不重读，false沿用历史参数形状。"""

    # 源码准入使用受控输入；冻结草稿仍调用真实SQL，重试前删除一项以识别意外重新冻结。
    seed_replacement(workspace)
    engine = workspace.engine
    engine.store.get_system = Mock(return_value=SimpleNamespace(source_version=None))
    engine.store.source_scan_matches_configured_version = Mock(return_value=True)
    engine.artifacts = SimpleNamespace(read=Mock(return_value=SimpleNamespace(scan_id="scan-1", baseline=None, entries=[])))
    engine._resolve_entry = Mock(return_value=SimpleNamespace(entry_id="query-1"))
    engine._input_contract = Mock(return_value=workspace.original.input_contract)
    engine._source_scopes = Mock(return_value=workspace.handoff.source_scopes)
    engine.require_generation_contracts = Mock()
    engine.handoffs = SimpleNamespace(request_scope=Mock(return_value=nullcontext()),
        find_request_receipt=Mock(return_value=None), write=Mock())
    monkeypatch.setattr("opentest.application.case_template_v4.current_employee", Mock(return_value=SimpleNamespace(user_id="employee-a")))
    request = CaseTemplateGenerationStartRequest(operation_id="query-1", baseline_id="baseline-one",
        request_id="request-replace-1", replace_existing_drafts=replace)
    reference = workspace.handoff.knowledge_dependencies[0]
    started = engine.start("orders", request, knowledge_ref=reference)
    assert started.replaced_case_drafts == (current_drafts(workspace) if replace else None)
    receipt = started.request_receipts[0]
    assert ("replace_existing_drafts" in receipt.parameters) == replace
    engine.handoffs.find_request_receipt.return_value = (started, receipt)
    workspace.database.execute("DELETE FROM ot_case_draft WHERE case_id='case-public'")
    assert engine.start("orders", request, knowledge_ref=reference) == started
    with pytest.raises(CaseTemplateWriteConflictError):
        engine.start("orders", request.model_copy(update={"replace_existing_drafts": not replace}), knowledge_ref=reference)


@pytest.mark.parametrize("replace", [False, True])
def test_task_creation_identity_only_adds_explicit_replacement(replace):
    """顶层Task的case_request与handoff回执一致：默认false不改变历史身份，true参与比较。"""

    application = OpenTestApplication.__new__(OpenTestApplication)
    application.tasks = SimpleNamespace(create_business_record=Mock())
    request = CaseTemplateGenerationStartRequest(operation_id="query-1", baseline_id="baseline-one",
        request_id="request-identity-1", replace_existing_drafts=replace)
    application._prepare_case_start_task("orders", request)
    # 检查真实构造的任务请求，避免只检查Pydantic默认值却遗漏任务层精确比较。
    created = application.tasks.create_business_record.call_args.args[0]
    assert ("replace_existing_drafts" in created.result["case_request"]) == replace


@pytest.mark.parametrize("replace", [False, True])
@pytest.mark.parametrize("handoff_status,task_status", [
    ("COMPLETED", TaskStatus.COMPLETED), ("PARTIAL", TaskStatus.PARTIAL), ("BLOCKED", TaskStatus.FAILED),
])
def test_terminal_start_replay_keeps_safe_replacement_display(workspace, replace, handoff_status, task_status):
    """启动响应未知后重放终态只返回安全替换标识，部分结果仍可正确标明原稿保留。"""

    # 模拟已完成handoff；真实生成及事务测试在上方覆盖，此处仅替代当前Case可见性读取。
    handoff = workspace.handoff.model_copy(update={"status": handoff_status,
        "replaced_case_drafts": [] if replace else None})
    task = TaskRecord(task_id="task-0123456789abcdef", operation="case-generation", system_id="orders",
        trace_id="replay-test", status=task_status, active_handoff_id=handoff.handoff_id,
        ended_at=handoff.updated_at,
        result={"case_request": {"replace_existing_drafts": replace, "operation_id": "query-1",
                                 "source_revision": "request-content-not-for-summary"},
                "draft_submission": {"title": "private-draft-not-for-replay"}})
    application = OpenTestApplication.__new__(OpenTestApplication)
    application.case_template_v4 = SimpleNamespace(_current_handoff_cases=Mock(return_value={"cases": []}))
    replay = application._case_preparation_result(task, handoff)
    # 前端状态标签需要任务类型与原生布尔值；不得通过透传result解决显示问题。
    assert replay["task"]["operation"] == "case-generation"
    assert replay["task"]["status"] == task_status.value
    assert replay["task"]["result"] == {"case_request": {"replace_existing_drafts": replace}}
    assert replay["task"]["result"]["case_request"]["replace_existing_drafts"] is replace
    assert replay["handoff"] is None and replay["cases"] == []
    assert "request-content-not-for-summary" not in json.dumps(replay)
    assert "private-draft-not-for-replay" not in json.dumps(replay)
