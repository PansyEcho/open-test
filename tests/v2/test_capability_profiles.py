"""验证声明式能力Profile及生产控制流业务身份硬编码门禁。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from opentest.adapters.knowledge_store import GitKnowledgeStore
from opentest.adapters.source_analysis import SourceScanArtifactStore
from opentest.adapters.sqlite_index import SqliteKnowledgeIndex
from opentest.application.capability_profiles import (
    CapabilityProfile,
    CapabilityProfileRegistry,
    OperationAliasProfile,
    default_capability_profiles,
)
from opentest.application.operations import OperationCapabilityCatalog
from opentest.domain.models import (
    EntryPoint,
    KnowledgeNodeKind,
    OperationCapability,
    OperationFieldEvidence,
    OperationKind,
    OperationMutability,
)


PROJECT_ROOT = Path(__file__).parents[2]
CONTROL_FLOW_FILES = (
    "opentest/application/operations.py",
    "opentest/application/foundation.py",
    "opentest/application/resources.py",
    "opentest/application/create_order_mvp.py",
    "opentest/application/scenarios.py",
    "opentest/adapters/knowledge_tracing.py",
    "opentest/adapters/qa_worker.py",
)
IDENTITY_NAMES = {"system_id", "entry_node_id", "source_id", "tool_id", "operation_id", "job_name"}


def _expression_names(node: ast.AST) -> set[str]:
    """收集条件表达式引用的变量和属性名称。

    Args:
        node: 需要检查的Python AST表达式。

    Returns:
        表达式内全部变量名和属性末段名称。
    """

    return {
        item.id if isinstance(item, ast.Name) else item.attr
        for item in ast.walk(node)
        if isinstance(item, (ast.Name, ast.Attribute))
    }


def _is_business_identity_literal(node: ast.AST) -> bool:
    """判断表达式是否把具体系统、入口、工具或Job身份写进代码。

    Args:
        node: 比较运算的一侧或字符串匹配参数。

    Returns:
        字符串或大写常量明显表达业务身份时为True。
    """

    if isinstance(node, ast.Name):
        return node.id.isupper() and any(token in node.id for token in ("SYSTEM", "ENTRY", "TOOL", "FACADE", "JOB"))
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    value = node.value
    return bool(
        value.startswith(("facade:", "job:", "resource:", "semantic:"))
        or re.search(r"[A-Za-z][\w.$]*#[A-Za-z]\w*", value)
        or re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+){2,}", value)
    )


def _hardcoded_identity_branches(path: Path) -> list[str]:
    """返回一个生产模块中依据具体业务身份进行控制流选择的位置。

    Args:
        path: 待解析的Python生产源码路径。

    Returns:
        可直接定位的行号和表达式摘要；空列表表示通过门禁。
    """

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            # 一侧引用通用身份变量、另一侧写死业务字面量或常量，就是被禁止的运行时分支。
            has_identity = any(_expression_names(operand) & IDENTITY_NAMES for operand in operands)
            has_literal = any(_is_business_identity_literal(operand) for operand in operands)
            if has_identity and has_literal:
                violations.append(f"{path.name}:{node.lineno}:{ast.unparse(node)}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in {"startswith", "endswith"} or not node.args:
                continue
            # 字符串前后缀同样能隐藏具体Facade/Job判断，必须使用Profile提供的动态值。
            receiver_names = _expression_names(node.func.value)
            if receiver_names & IDENTITY_NAMES and _is_business_identity_literal(node.args[0]):
                violations.append(f"{path.name}:{node.lineno}:{ast.unparse(node)}")
    return violations


def test_two_unrelated_profiles_use_the_same_operation_name_path(tmp_path: Path) -> None:
    """两个无关系统应通过同一目录逻辑应用各自声明的操作别名。"""

    profiles = CapabilityProfileRegistry(
        [
            CapabilityProfile(
                profile_id="alpha-profile",
                system_ids=["alpha.system.core"],
                operation_aliases=[OperationAliasProfile(source_pattern="*.AlphaFacade#find", aliases=["查找甲对象"])],
            ),
            CapabilityProfile(
                profile_id="beta-profile",
                system_ids=["beta.system.core"],
                operation_aliases=[OperationAliasProfile(source_pattern="*.BetaFacade#find", aliases=["查找乙对象"])],
            ),
        ]
    )
    store = GitKnowledgeStore(tmp_path / "knowledge")
    catalog = OperationCapabilityCatalog(store, SourceScanArtifactStore(store.root), profiles=profiles)
    entries = [
        EntryPoint(
            entry_id="facade:example.AlphaFacade#find",
            system_id="alpha.system.core",
            kind=KnowledgeNodeKind.FACADE,
            display_name="AlphaFacade#find",
            source_id="example.AlphaFacade#find",
            source_path="AlphaFacade.java",
        ),
        EntryPoint(
            entry_id="facade:example.BetaFacade#find",
            system_id="beta.system.core",
            kind=KnowledgeNodeKind.FACADE,
            display_name="BetaFacade#find",
            source_id="example.BetaFacade#find",
            source_path="BetaFacade.java",
        ),
    ]

    # 同一通用命名函数只从Profile获得差异，不包含具体系统或Facade分支。
    names = [catalog._business_name(entry) for entry in entries]
    assert names[0].endswith("查找甲对象")
    assert names[1].endswith("查找乙对象")
    assert default_capability_profiles().profile_for_system("ifightchainsaas.java.refund.core") is not None


def test_operation_v2_contract_has_no_safe_default_channel() -> None:
    """V2能力模型不得重新引入可被后端盲目注入的安全默认值字段。"""

    assert OperationCapability.model_fields["contract_version"].default == "operation-capability/v2"
    assert "safe_defaults" not in OperationCapability.model_fields


def test_unprofiled_fallback_is_limited_to_the_legacy_scenario_api() -> None:
    """未配置系统只能复用旧场景模板，不能获得追踪、Worker或真实MVP能力。"""

    profiles = default_capability_profiles()

    # fallback的调用面由不同注册表方法显式隔离，避免同名入口扩大为真实执行授权。
    assert profiles.legacy_workflow("unprofiled.system.core", "facade:TradeFacade#createOrder") is None
    assert profiles.legacy_scenario_workflow(
        "unprofiled.system.core",
        "facade:TradeFacade#createOrder",
    ) is not None
    assert profiles.legacy_scenario_workflow(
        "ifightchainsaas.java.refund.core",
        "facade:TradeFacade#createOrder",
    ) is None


def test_relation_query_ranking_prefers_matching_input_and_requested_output(tmp_path: Path) -> None:
    """关系型查询应优先同时接收给定条件并返回目标字段的只读操作。"""

    index = SqliteKnowledgeIndex(tmp_path / "index.sqlite")
    query_capability = OperationCapability(
        operation_id="facade:example.QueryFacade#queryList",
        system_id="example.system.core",
        business_name="QueryFacade#queryList · 查询 列表",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_fields=[OperationFieldEvidence(field_path="ticket", field_name="ticket", description="票号")],
        output_fields=[OperationFieldEvidence(field_path="refundNo", field_name="refundNo", description="退票单号")],
        source_scan_id="scan-ranking",
    )
    detail_capability = query_capability.model_copy(
        update={
            "operation_id": "facade:example.DetailFacade#queryDetail",
            "business_name": "DetailFacade#queryDetail · 查询 详情",
            "input_fields": [
                OperationFieldEvidence(field_path="refundNo", field_name="refundNo", description="退票单号")
            ],
        }
    )
    query = "查询票号为TEST001的退票单号有哪些"

    # 动作词相同的情况下，输入与输出角色证据必须让真正可满足请求的操作胜出。
    query_score = index._operation_match_score(
        query,
        query_capability.operation_id,
        query_capability.business_name,
        query_capability.model_dump_json(),
    )
    detail_score = index._operation_match_score(
        query,
        detail_capability.operation_id,
        detail_capability.business_name,
        detail_capability.model_dump_json(),
    )
    assert index._operation_query_roles(query) == ("票号", "退票单号")
    assert query_score > detail_score


def test_production_control_flow_does_not_branch_on_business_identity_literals() -> None:
    """生产控制流不得再比较具体系统、Facade、方法、工具或Job业务身份。"""

    violations = [
        violation
        for relative_path in CONTROL_FLOW_FILES
        for violation in _hardcoded_identity_branches(PROJECT_ROOT / relative_path)
    ]
    assert violations == []

    # 浏览器通用工作区也不能重新出现特定系统常量或直接字面量比较。
    browser_source = (PROJECT_ROOT / "opentest/web/app.js").read_text(encoding="utf-8")
    assert "BOOKING_CORE_SYSTEM_ID" not in browser_source
    assert re.search(r"system_id\s*[!=]==?\s*[\"'][a-z0-9.-]+[\"']", browser_source) is None
