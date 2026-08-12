"""验证Booking.Core核心生命周期Suite、Case与公开Oracle目录保持闭合。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml
import pytest

from opentest.adapters.case_store import GitCaseStore
from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.application.regression import RegressionSuiteReader
from opentest.domain.models import KnowledgeNodeKind, KnowledgeStatus, LifecycleCaseStep


SYSTEM_ROOT = (
    Path(__file__).parents[2]
    / "open-test-knowledge"
    / "systems"
    / "train-booking-core"
)
KNOWLEDGE_ROOT = SYSTEM_ROOT.parents[1]
CASE_ROOT = SYSTEM_ROOT / "cases" / "custom"
SUITE_PATH = SYSTEM_ROOT / "cases" / "suites" / "core-order-lifecycle.yaml"
CATALOG_PATH = SYSTEM_ROOT / "oracles" / "catalog.yaml"

EXPECTED_CATEGORY_COUNTS = {
    "realtime-distribution-success": 2,
    "realtime-distribution-fallback": 2,
    "occupy-full-success": 2,
    "grab-immediate-failure": 3,
    "occupy-failure-second-dispatch": 2,
    "issue-rejection": 4,
    "mtr-orders": 2,
    "hkd-multi-passenger": 3,
    "connected-orders": 3,
    "cancellation": 4,
    "revoke-timeout": 2,
    "ht-idempotency": 2,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """读取一个受版本管理的YAML映射。

    Args:
        path: 待验证的知识、Case或目录文件。

    Returns:
        YAML顶层映射；测试失败时保留具体文件路径。
    """

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"YAML root must be a mapping: {path}"
    return payload


def _load_cases() -> list[dict[str, Any]]:
    """按文件名前缀顺序读取31个自定义业务Case。

    Returns:
        保持业务矩阵顺序的Case映射列表。
    """

    case_paths = sorted(CASE_ROOT.glob("*.yaml"))
    return [_load_yaml(path) for path in case_paths]


def test_lifecycle_suite_has_exact_12_categories_and_31_blocked_variants() -> None:
    """核心Suite必须精确覆盖用户确认的12类31项且不伪造可执行状态。"""

    cases = _load_cases()
    suite = _load_yaml(SUITE_PATH)

    # 稳定ID、分类计数和Suite引用必须形成一一对应的有序闭包。
    variant_ids = [case["variant_id"] for case in cases]
    category_counts = Counter(case["category_id"] for case in cases)
    assert len(cases) == 31
    assert len(set(variant_ids)) == 31
    assert dict(category_counts) == EXPECTED_CATEGORY_COUNTS
    assert suite["variants"] == variant_ids

    # 未提供QA Fixture和业务口径前，任何Case都不能变成绿色可执行资产。
    assert suite["lifecycle"] == "blocked"
    for case in cases:
        assert case["lifecycle"] == "blocked"
        assert case["missing_conditions"]
        step_ids = [step["step_id"] for step in case["steps"]]
        assert case["fixed_execution_order"] == step_ids


def test_production_reader_and_case_store_close_all_lifecycle_references() -> None:
    """交付Suite和31个自定义Case必须通过生产Reader与CaseStore解析。"""

    suite = RegressionSuiteReader(KNOWLEDGE_ROOT).load(
        "train-booking-core",
        "suite:train-booking-core:core-order-lifecycle-v2",
    )
    case_store = GitCaseStore(GitKnowledgeStore(KNOWLEDGE_ROOT))
    compiled_variants = {
        variant.variant_id: variant
        for variant in case_store.list_variants("train-booking-core")
        if variant.variant_id in set(suite.variants)
    }

    # 生产读取链必须闭合全部ID，并把Git缺口编译为明确BLOCKED，而不是“未编译”占位。
    assert set(compiled_variants) == set(suite.variants)
    assert len(suite.global_jobs) == 5
    assert all(variant.lifecycle == "blocked" for variant in compiled_variants.values())
    assert all(variant.replay["missing_conditions"] for variant in compiled_variants.values())
    assert all(
        placeholder.startswith("${qa.fixtures.")
        for variant in compiled_variants.values()
        for step in variant.steps
        for placeholder in _fixture_placeholders(step.model_dump(mode="python"))
    )


def test_first_ebk_canary_compiles_response_and_business_oracle_contracts() -> None:
    """首条EBK金丝雀必须编译响应断言、状态流转和逐乘客Item契约。"""

    case_store = GitCaseStore(GitKnowledgeStore(KNOWLEDGE_ROOT))
    variant = case_store.get_variant(
        "train-booking-core",
        "variant:core-order-lifecycle:001-realtime-ebk-success",
    )
    steps = {step.step_id: step for step in variant.steps}

    # 工具结果与数据库观察是两类独立证据，响应断言必须紧跟相应业务入口。
    assert [step.step_id for step in variant.steps] == [
        "execute-create",
        "assert-create",
        "observe-ticketing",
        "observe-collection",
        "execute-issue",
        "assert-issue",
        "observe-order",
        "observe-items",
        "observe-redis-done",
        "observe-mq-effect",
    ]
    assert steps["assert-create"].action == "assert"
    assert steps["assert-create"].assertions["$.response.result.orderSerialId"] == {"op": "not_null"}
    assert steps["assert-issue"].assertions["$.response.result.msgCode"] == 106100

    # 真实分单后先证明TICKETING，再在出票回填后证明ISSUE_SUCCESS。
    ticketing_oracle = steps["observe-ticketing"].oracle
    issued_oracle = steps["observe-order"].oracle
    assert ticketing_oracle is not None
    assert issued_oracle is not None
    assert ticketing_oracle.assertions["rows[0].orderState"] == 5
    assert issued_oracle.assertions["rows[0].orderState"] == 6
    assert steps["observe-collection"].oracle is not None
    assert steps["observe-collection"].oracle.assertions == {"rowCount": 0, "rows": []}

    # Item按业务字段无序匹配，公共HT/TX、QA环境和非空itemId对每一行生效。
    item_oracle = steps["observe-items"].oracle
    assert item_oracle is not None
    unordered_match = item_oracle.assertions["rows"]
    assert unordered_match["op"] == "rows_unordered_match"
    assert unordered_match["value"] == {
        "expected_rows": "${qa.fixtures.domestic_ebk.expected_issue_items}",
        "common_fields": {
            "orderSerialNo": "${steps.execute-create.output.response.result.orderSerialId}",
            "transactionSerialNo": "${steps.execute-create.output.response.result.transactionId}",
            "deleted": 0,
            "environment": "qa",
        },
        "non_null_fields": ["itemId"],
    }

    # MQ没有轨迹端点时只声明效果证据，不能把directVerified=false伪装成传输证明。
    mq_oracle = steps["observe-mq-effect"].oracle
    assert mq_oracle is not None
    assert mq_oracle.kind == "mq"
    assert mq_oracle.operation_id == "mq.trace_match"
    assert mq_oracle.assertions == {
        "directVerified": False,
        "evidenceMode": "downstream_effect_only",
    }


def test_first_ebk_issue_request_uses_fixture_base_and_runtime_order_keys() -> None:
    """首条EBK出票步骤必须复用Fixture请求并注入真实创单HT与TX。"""

    case_store = GitCaseStore(GitKnowledgeStore(KNOWLEDGE_ROOT))
    variant = case_store.get_variant(
        "train-booking-core",
        "variant:core-order-lifecycle:001-realtime-ebk-success",
    )
    issue_step = next(step for step in variant.steps if step.step_id == "execute-issue")

    assert issue_step.params == {
        "request_base": "${qa.fixtures.domestic_ebk.issue_request}",
        "request_overrides": {
            "serialId": "${steps.execute-create.output.response.result.orderSerialId}",
            "transactionSerialNo": "${steps.execute-create.output.response.result.transactionId}",
        },
    }
    assert variant.replay["cleanup_policy"] == {
        "mode": "EXTERNAL_FIXTURE_OWNER",
        "key": "${steps.execute-create.output.response.result.orderSerialId}",
        "reason": "",
    }


def test_lifecycle_assert_rejects_input_that_compiler_would_ignore() -> None:
    """生命周期响应断言不得夹带会在编译时被静默丢弃的input。"""

    with pytest.raises(ValueError, match="lifecycle assert step requires only"):
        LifecycleCaseStep(
            step_id="assert-unsafe",
            action="assert",
            input={"request": "ignored"},
            assertions={"$.success": True},
        )
    with pytest.raises(ValueError, match="lifecycle execute step requires only"):
        LifecycleCaseStep(
            step_id="execute-unsafe",
            action="execute",
            tool_id="facade.trade.create_order",
            assertions={"$.success": True},
        )


def test_production_knowledge_store_reads_all_lifecycle_nodes() -> None:
    """生产知识存储必须能解析全部生命周期文档及其受控可信状态。"""

    knowledge_store = GitKnowledgeStore(KNOWLEDGE_ROOT)

    # 直接遍历生产references目录，防止局部测试绕过非法frontmatter状态。
    nodes = knowledge_store.list_nodes("train-booking-core")
    lifecycle_nodes = {
        node.node_id: node
        for node, path, _ in nodes
        if "core-lifecycle" in path.parts
    }

    assert set(lifecycle_nodes) == {
        "flow:core-order-lifecycle:oracle-boundaries-v2",
        "flow:core-order-lifecycle:recovery-flows",
        "flow:core-order-lifecycle:scenario-matrix-v2",
    }

    # 含待确认口径的策划型知识只能保持推断状态，场景矩阵归入公共业务逻辑。
    recovery_node = lifecycle_nodes["flow:core-order-lifecycle:recovery-flows"]
    scenario_matrix_node = lifecycle_nodes["flow:core-order-lifecycle:scenario-matrix-v2"]
    assert recovery_node.status == KnowledgeStatus.INFERRED
    assert scenario_matrix_node.status == KnowledgeStatus.INFERRED
    assert scenario_matrix_node.kind == KnowledgeNodeKind.COMMON_LOGIC


def _fixture_placeholders(value: Any) -> list[str]:
    """递归收集编译后步骤中的Fixture占位符。

    Args:
        value: ScenarioStep序列化后的任意JSON兼容值。

    Returns:
        所有仍以`${...}`表示的Fixture引用。
    """

    if isinstance(value, dict):
        return [item for child in value.values() for item in _fixture_placeholders(child)]
    if isinstance(value, list):
        return [item for child in value for item in _fixture_placeholders(child)]
    if isinstance(value, str) and value.startswith("${qa.fixtures."):
        return [value]
    return []


def test_case_oracles_match_public_catalog_and_mq_is_effect_only() -> None:
    """每个业务Oracle必须匹配固定资源、参数目录和真实证据等级。"""

    cases = _load_cases()
    suite = _load_yaml(SUITE_PATH)
    catalog = _load_yaml(CATALOG_PATH)
    operations = catalog["operations"]

    # 公开目录必须完整覆盖11个逻辑操作和resource.probe的5个独立资源绑定。
    operation_ids = {operation["operation_id"] for operation in operations}
    operation_contracts = {
        (operation["operation_id"], operation["resource_id"]): operation
        for operation in operations
    }
    assert len(operations) == 15
    assert len(operation_ids) == 11
    assert len(operation_contracts) == 15
    assert set(suite["approved_operation_ids"]) == operation_ids

    oracle_count = 0
    for case in cases:
        for step in case["steps"]:
            if step["action"] != "oracle":
                continue
            oracle_count += 1
            oracle = step["oracle"]
            contract = operation_contracts[(oracle["operation_id"], oracle["resource_id"])]
            assert set(step["input"]) == set(contract["parameter_names"])
            if oracle["kind"] == "MQ":
                assert oracle["evidence_mode"] == "EFFECT_ONLY"
                assert contract["evidence_level"] == "effect_only"
            else:
                assert oracle["evidence_mode"] == "DIRECT"
                assert contract["evidence_level"] == "direct"
    assert oracle_count == 91


def test_job_cases_keep_qa_environment_and_global_confirmation_guards() -> None:
    """所有含Job工具的Case必须在QA地址和全局影响门禁补齐前保持阻塞。"""

    job_cases: list[dict[str, Any]] = []
    for case in _load_cases():
        tool_ids = {
            step.get("tool_id", "")
            for step in case["steps"]
            if step["action"] == "execute"
        }
        if any(tool_id.startswith("job.") for tool_id in tool_ids):
            job_cases.append(case)

    assert len(job_cases) == 5
    for case in job_cases:
        # 当前扫描Job脚本仍绑定test地址，因此必须同时要求QA重绑和一次性确认。
        assert "qa_job_url_binding" in case["missing_conditions"]
        assert "global_job_confirmation_token" in case["missing_conditions"]
        assert case["global_job_guard"] == {
            "required": True,
            "impact_preview": "required",
            "one_time_confirmation": "required",
            "qa_only": True,
        }


def test_public_assets_do_not_expose_infrastructure_secrets_or_query_templates() -> None:
    """Git知识资产不得包含连接秘密、任意SQL或Redis Key模板。"""

    checked_paths = [CATALOG_PATH, SUITE_PATH, *sorted(CASE_ROOT.glob("*.yaml"))]
    forbidden_markers = (
        "mysql_password",
        "redis_password",
        "jdbc_url",
        "connection_string",
        "key_template",
        "select * from",
        "authorization:",
        "access_token:",
    )
    for path in checked_paths:
        # 检查公开文件原文，避免解析YAML后遗漏注释或未建模字段中的泄露。
        normalized = path.read_text(encoding="utf-8").lower()
        assert not any(marker in normalized for marker in forbidden_markers), path
