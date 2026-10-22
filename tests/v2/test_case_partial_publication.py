"""验证局部缺口保留独立 Case：真实编译、个人草稿保存和投影全程离线。"""

from __future__ import annotations

import json
import socket
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.adapters.case_template_v4_store import CaseTemplateHandoffStoreV4
from opentest.application.case_template_v4 import CaseTemplateV4Service
from opentest.application.publication import PublicationService
from opentest.domain.case_template_v4 import (
    CaseTemplateGenerationV4,
    CaseTemplateHandoffV4,
    CaseTemplatePublicationRequest,
    CaseTemplateSubmission,
    RuntimeFunctionRegistry,
)
from opentest.domain.errors import KnowledgeNotFoundError
from opentest.domain.models import KnowledgeQuestion, OperationInputKnowledgeContract
from opentest.domain.publication import CaseDraftUpdate, PublicationScope


SYSTEM_ID = "example.catalog"
TARGET_ID = "facade:example.Catalog#inspect"
QUERY_ID = "facade:example.Catalog#find"
MISSING_ID = "facade:example.Audit#observe"
SOURCE_PATH = "src/Catalog.java"


def _partial_submission() -> CaseTemplateSubmission:
    """返回八条独立场景和一个观察缺口场景；所有业务名称、证据均为合成数据。"""

    evidence = [{"source_system_id": SYSTEM_ID, "path": SOURCE_PATH, "line": 1,
                 "symbol": "Catalog#find"}]
    # 每个场景复用同一个动态查询函数，验证局部观察缺口不会污染无关函数依赖。
    templates = [{
        "template_id": name, "title": name, "coverage_kind": "business", "combination": "each",
        "data_calls": [{"call_id": "item", "function_name": "find_item"}],
        "request_bindings": [{"field": "itemId", "source": {
            "kind": "data_output", "call_id": "item", "output_name": "item_id"}}],
        "oracles": [{"oracle_id": "response_check", "channel": "response",
                     "assertions": [{"actual_path": "success", "operator": "exists"}]}],
        "evidence": evidence,
    } for name in [*[f"case.safe_{index}" for index in range(8)], "case.observation_missing"]]
    return CaseTemplateSubmission.model_validate({
        "data_functions": [{
            "name": "find_item", "description": "在执行时读取一个真实条目，不固化业务标识。",
            "steps": [{"step_id": "lookup", "operation": "runtime_call", "function_id": QUERY_ID}],
            "outputs": [{"output_name": "item_id", "step_id": "lookup", "path": "itemId"}],
            "evidence": evidence,
        }],
        "case_templates": templates,
        "unresolved": [{"unresolved_id": "observation_missing", "owner_type": "case_template",
                        "owner_name": "case.observation_missing", "field_path": "oracles",
                        "reason": "该分支需要尚未解析的独立观察接口。"}],
    })


def _source_contract() -> OperationInputKnowledgeContract:
    """返回合成固定扫描的 READY 契约；业务标识必须由 DATA 输出提供。"""

    return OperationInputKnowledgeContract.model_validate({
        "target_id": TARGET_ID, "source_scan_id": "scan-partial", "status": "READY",
        "request_schema": {"type": "object", "properties": {"itemId": {"type": "string"}},
                           "required": ["itemId"], "additionalProperties": False},
        "fields": [{"path": "itemId", "field_name": "itemId", "schema": {"type": "string"},
                    "required": True, "business_identity": True, "requirement_marker": "@required"}],
    })


def test_available_publication_compiles_and_saves_only_independent_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """局部裸 owner 缺口允许保存八条个人 Case，并保持精确依赖及请求去重。

    Args:
        tmp_path: pytest 隔离目录，仅保存临时 handoff 和合成源码审计。
        monkeypatch: 替换外部数据库、扫描读取边界，并禁止网络连接。
    Returns:
        None；真实编译、发布、个人草稿投影及重试断言全部通过时成功。
    Side Effects:
        只写临时目录与内存；不构造执行器、不调用任何业务或测试环境。
    """

    # 网络若被任何新增隐式路径触发立即失败，防止离线回归访问测试环境。
    connection = Mock(side_effect=AssertionError("partial publication must remain offline"))
    monkeypatch.setattr(socket.socket, "connect", connection)
    store = Mock()
    store.system_transaction.side_effect = lambda system_id: nullcontext()
    generations = Mock()
    immutable: dict[str, CaseTemplateGenerationV4] = {}
    draft_rows: dict[str, dict] = {}

    def read_generation(system_id: str, generation_id: str) -> CaseTemplateGenerationV4:
        """按系统和 Generation ID 返回内存产物；尚未写入时抛真实存储的不存在异常。"""

        # 首次发布需要走新增分支，后续同请求重试应复用既有资产。
        if generation_id not in immutable:
            raise KnowledgeNotFoundError("isolated generation does not exist")
        generation = immutable[generation_id]
        assert generation.system_id == system_id
        return generation

    def write_generation(generation: CaseTemplateGenerationV4) -> CaseTemplateGenerationV4:
        """模拟不可变写入并严格回读；保留默认创建时间及 DSL 字段存在性。"""

        assert generation.generation_id not in immutable
        payload = generation.model_dump(mode="json", exclude_unset=True)
        # 生产 GenerationStore 同样补回默认创建时间，避免重读生成不同资产。
        payload["created_at"] = generation.created_at.isoformat()
        persisted = CaseTemplateGenerationV4.model_validate(payload)
        immutable[generation.generation_id] = persisted
        return persisted

    generations.get.side_effect = read_generation
    generations.write.side_effect = write_generation
    handoffs = CaseTemplateHandoffStoreV4(tmp_path)
    service = CaseTemplateV4Service(store, Mock(), generations, handoffs)
    contract = _source_contract()
    output_schema = {"type": "object", "properties": {"success": {"type": "boolean"}}}
    registry = RuntimeFunctionRegistry.model_validate({"functions": [{
        "function_id": QUERY_ID, "kind": "dsf", "description": "读取条目", "read_only": True,
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {"itemId": {"type": "string"}}},
        "allowed_phases": ["DATA", "ORACLE"], "source_system_id": SYSTEM_ID, "provider_ref": QUERY_ID,
    }]})
    handoff = CaseTemplateHandoffV4.model_validate({
        "handoff_id": "case-template-handoff-" + "a" * 20,
        "generation_id": "case-template-generation-" + "b" * 20,
        "system_id": SYSTEM_ID, "entry_id": TARGET_ID, "source_scan_id": "scan-partial",
        "baseline_id": "baseline-example", "owner_user_id": "employee-example",
        "status": "WAITING_FOR_AGENT", "revision": 4, "execution_mode": "generate_and_verify",
        "source_scopes": [{"source_system_id": SYSTEM_ID, "source_scan_id": "scan-partial",
                           "source_baseline": {"source_path": str(tmp_path)},
                           "selected_operation_ids": [TARGET_ID, QUERY_ID, MISSING_ID]}],
        "knowledge_dependencies": [{"baseline_interface_id": index, "interface_id": index + 10,
                                    "contract_revision": 0} for index in (1, 2, 3)],
    })
    # 只替换固定扫描/源码读取边界，编译器、问题合并、资格判断和发布方法均使用真实代码。
    service._require_current_source_scopes = Mock()
    service._handoff_contract = Mock(return_value=contract)
    service._runtime_capabilities = Mock(return_value=[
        SimpleNamespace(system_id=SYSTEM_ID, operation_id=TARGET_ID, executable=True,
                        publication_output_schema=output_schema, output_fields=[]),
        SimpleNamespace(system_id=SYSTEM_ID, operation_id=QUERY_ID, executable=True),
    ])
    service.registries.runtime_registry = Mock(return_value=registry)
    service._evidence_source_texts = Mock(return_value={SYSTEM_ID: {SOURCE_PATH: "1\tString find();"}})
    handoffs.audit_path(handoff.handoff_id, SYSTEM_ID).write_text(json.dumps({
        "tool": "read_source", "path": SOURCE_PATH, "start_line": 1, "end_line": 1,
    }) + "\n", encoding="utf-8")
    submission = _partial_submission()
    compiled = service._compile_draft(handoff, submission, [])
    questions = service._merge_case_questions(handoff, [KnowledgeQuestion(
        question_id="diagnostic-observation", system_id=SYSTEM_ID,
        title="独立观察缺口", detail="该分支观察接口尚缺失。", source="case_template",
        category="case_template_business_rule", affected_target_ids=["case.observation_missing"],
    )], submission, [], set())
    assert len(compiled.variants) == 8
    assert [(issue.code, issue.owner) for issue in compiled.issues] == [
        ("UNRESOLVED_BLOCKER", "case_template:case.observation_missing")]
    assert len(questions) == 2
    handoff = handoff.model_copy(update={
        "status": service._draft_status(submission, compiled.issues, questions), "recoverable": True,
        "draft_submission": submission, "draft_variants": compiled.variants,
        "validation_issues": compiled.issues, "questions": questions,
    })
    assert handoff.status == "FAILED"
    assert service._allowed_publication_modes(handoff) == ["available"]
    handoffs.write(handoff)

    # PublicationService 仍执行正式范围/CAS/不可变产物校验，仅底层数据库读写换成内存行。
    publication_store = Mock()
    operations = {1: TARGET_ID, 2: QUERY_ID, 3: MISSING_ID}
    publication_store.dependency_interface.side_effect = lambda identity: {
        "baseline_id": handoff.baseline_id, "system_id": SYSTEM_ID, "operation_id": operations[identity]}

    def stored_generation(generation_id: str) -> dict:
        """按 Generation ID 返回数据库形状的固定产物，不跳过领域模型严格回读。"""

        generation = immutable[generation_id]
        payload = generation.model_dump(mode="json", exclude_unset=True)
        # 默认创建时间属于持久资产，不能因 exclude_unset 在投影时重新生成。
        payload["created_at"] = generation.created_at.isoformat()
        return {"baseline_id": generation.baseline_id, "system_id": generation.system_id,
                "owner_user_id": generation.owner_user_id, "generation": payload}

    def save_draft(scope: PublicationScope, generation_id: str, update: CaseDraftUpdate) -> None:
        """按授权范围、固定产物及 Case 绑定建立内存草稿行；供真实单项投影消费。"""

        draft_rows[update.binding.case_id] = {
            "case_id": update.binding.case_id, "system_id": scope.system_id, "baseline_id": scope.baseline_id,
            "baseline_interface_id": update.baseline_interface_id, "operation_id": TARGET_ID,
            "draft_generation_id": generation_id, "draft_variant_id": update.binding.variant_id,
            "draft_status": "READY", "draft_revision": 1, "publication_revision": 0,
            "expected_publication_revision": 0,
        }

    publication_store.generation.side_effect = stored_generation
    publication_store.ensure_case.return_value = {"draft_revision": 0, "publication_revision": 0}
    publication_store.put_case_draft.side_effect = save_draft
    publication_store.get_item.side_effect = lambda scope, kind, case_id: draft_rows.get(case_id)
    monkeypatch.setattr("opentest.application.publication.PublicationStore", lambda metadata: publication_store)
    request = CaseTemplatePublicationRequest(
        request_id="offline-partial-publication", expected_revision=4, mode="available")
    generation = service.publish(handoff.handoff_id, request)
    repeated = service.publish(handoff.handoff_id, request)

    # 通过真实个人视图读取每条 Case，确认没有附带缺口模板/未调用观察接口或兄弟函数。
    scope = PublicationScope(system_id=SYSTEM_ID, baseline_id=handoff.baseline_id, user_id=handoff.owner_user_id)
    publications = PublicationService(store)
    cases = [publications.get_case(scope, case_id, "mine") for case_id in draft_rows]
    assert len(cases) == 8
    assert all(case.template_id.startswith("case.safe_") and not case.variant.blocked_reason for case in cases)
    assert all([function.name for function in case.data_functions] == ["find_item"] for case in cases)
    assert all({ref.baseline_interface_id for ref in case.knowledge_dependencies} == {1, 2} for case in cases)
    assert generation.status == "PARTIAL"
    assert handoffs.get(handoff.handoff_id).status == "PARTIAL"
    assert handoffs.get(handoff.handoff_id).revision == 5
    assert repeated == generation
    assert generations.write.call_count == 1
    assert publication_store.put_case_draft.call_count == 8
    connection.assert_not_called()
