"""验证Case Generation V4强类型DSL、通用编译和QA执行闭环。"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from opentest.adapters.codex_app_server import (
    CodexCaseTurnProcessSnapshot,
    CodexModelCatalog,
    CodexModelOption,
    CodexStartedTurn,
    CodexThreadSnapshot,
)
from opentest.adapters.case_template_v4_store import (
    CaseTemplateGenerationStoreV4,
    CaseTemplateHandoffStoreV4,
)
from opentest.adapters.registered_source_mcp import RegisteredSourceReader
from opentest.adapters.source_analysis import GitSourceRepository, SourceScanArtifactStore
from opentest.application.case_template_compiler_v4 import (
    CaseTemplateCompilerV4,
    CaseTemplateValidatorV4,
)
from opentest.application.case_template_executor_v4 import CaseTemplateExecutorV4
from opentest.application.case_template_registries import (
    CaseTemplateRegistryLoader,
    ValueFunctionEngine,
)
from opentest.application.case_template_v4 import (
    CaseTemplateV4RuntimeServices,
    CaseTemplateV4Service,
    default_case_template_environment_values,
)
from opentest.application.operations import OperationCapabilityCatalog
from opentest.application.operation_input_knowledge import OperationInputKnowledgeBuilder
from opentest.domain.case_template_v4 import (
    CaseOracleAssertion,
    CaseTemplateCompilationInput,
    CaseTemplateGenerationStartRequest,
    CaseTemplateGenerationV4,
    CaseTemplateHandoffV4,
    CaseTemplateSourceScope,
    CaseTemplateSubmission,
    DslValueSource,
    RuntimeFunctionDescriptor,
    RuntimeFunctionRegistry,
)
from opentest.domain.errors import ExecutionFailure, KnowledgeValidationError
from opentest.domain.models import (
    KnowledgeNode,
    KnowledgeNodeKind,
    OperationCapability,
    OperationExecutionRecord,
    OperationExecutionStatus,
    OperationFieldEvidence,
    OperationInputFieldKnowledge,
    OperationInputKnowledgeContract,
    OperationKind,
    OperationMutability,
    OperationProviderKind,
    SemanticAnalysisResult,
    SemanticFieldDefinition,
    SemanticTypeDefinition,
    SourceBaseline,
    SourceReference,
    RuntimeToolSettings,
)


SYSTEM_ID = "ifightchainsaas.java.refund.core"
BOOKING_SYSTEM_ID = "ifightchainsaas.java.booking.core"
SCAN_ID = "scan-refund-v4-golden"
CANCEL_ID = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#cancel"
QUERY_LIST_ID = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryList"
DETAIL_ID = "facade:com.ly.flight.chainsaas.refund.facade.RefundFacade#queryDetailByRefundNo"
DATABASE_ID = "database:ifightchainsaas.java.refund.core:itradecoredatasource"
TRADE_QUERY_LIST_ID = "facade:com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList"
GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "case-template-v4" / "refund-cancel-golden.json"


def _cancel_contract() -> OperationInputKnowledgeContract:
    """构造Golden使用的cancel READY输入知识契约。

    Returns:
        六个字符串字段及四个源码声明必填字段的严格契约。
    """

    names = ["traceId", "operator", "refundSerialNo", "cancelReasonId", "cancelReason", "cancelRemark"]
    required = {"refundSerialNo", "cancelReasonId", "cancelReason", "cancelRemark"}
    return OperationInputKnowledgeContract(
        target_id=CANCEL_ID,
        request_type="RefundCancelRequest",
        source_scan_id=SCAN_ID,
        status="READY",
        request_schema={
            "type": "object",
            "properties": {name: {"type": "string"} for name in names},
            "required": sorted(required),
            "additionalProperties": False,
        },
        fields=[
            OperationInputFieldKnowledge(
                path=name,
                field_name=name,
                schema={"type": "string"},
                required=name in required,
                business_identity=name == "refundSerialNo",
                requirement_marker="@required" if name in required else "",
            )
            for name in names
        ],
    )


def _query_list_contract() -> OperationInputKnowledgeContract:
    """构造与cancel结构不同的只读queryList输入契约。

    Returns:
        page和pageSize均必填的READY契约。
    """

    return OperationInputKnowledgeContract(
        target_id=QUERY_LIST_ID,
        request_type="RefundOrderQueryRequest",
        source_scan_id=SCAN_ID,
        status="READY",
        request_schema={
            "type": "object",
            "properties": {"page": {"type": "integer"}, "pageSize": {"type": "integer"}},
            "required": ["page", "pageSize"],
            "additionalProperties": False,
        },
        fields=[
            OperationInputFieldKnowledge(
                path=name,
                field_name=name,
                schema={"type": "integer"},
                required=True,
                requirement_marker="@required",
            )
            for name in ("page", "pageSize")
        ],
    )


def _golden_submission() -> CaseTemplateSubmission:
    """读取并严格解析新V4 cancel Golden DSL。

    Returns:
        只含data_functions、case_templates和unresolved的提交。
    """

    return CaseTemplateSubmission.model_validate_json(GOLDEN_PATH.read_text(encoding="utf-8"))


def _runtime_registry() -> RuntimeFunctionRegistry:
    """构造Golden需要的动态Operation Runtime目录。

    Returns:
        booking queryList、refund queryList、详情和扫描数据库四个受控函数。
    """

    booking_query_input = {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "default": 1},
            "pageSize": {"type": "integer", "default": 20},
        },
        "required": ["page", "pageSize"],
        "additionalProperties": False,
    }
    query_input = {
        "type": "object",
        "properties": {
            "traceId": {"type": "string"},
            "operator": {"type": "string"},
            "page": {"type": "integer", "default": 1},
            "pageSize": {"type": "integer", "default": 20},
            "orderState": {"type": "integer"},
            "platFormId": {"type": "string"},
        },
        "required": ["page", "pageSize", "platFormId"],
        "additionalProperties": False,
    }
    detail_input = {
        "type": "object",
        "properties": {
            "traceId": {"type": "string"},
            "operator": {"type": "string"},
            "refundSerialNo": {"type": "string"},
        },
        "additionalProperties": False,
    }
    return RuntimeFunctionRegistry(
        functions=[
            RuntimeFunctionDescriptor(
                function_id=TRADE_QUERY_LIST_ID,
                kind="dsf",
                description="查询booking订单列表",
                input_schema=booking_query_input,
                output_schema={},
                allowed_phases=["DATA", "ORACLE"],
                source_system_id=BOOKING_SYSTEM_ID,
                provider_ref=TRADE_QUERY_LIST_ID,
            ),
            RuntimeFunctionDescriptor(
                function_id=QUERY_LIST_ID,
                kind="dsf",
                description="查询退票单列表",
                input_schema=query_input,
                output_schema={},
                allowed_phases=["DATA", "ORACLE"],
                source_system_id=SYSTEM_ID,
                provider_ref=QUERY_LIST_ID,
            ),
            RuntimeFunctionDescriptor(
                function_id=DETAIL_ID,
                kind="dsf",
                description="查询退票单详情",
                input_schema=detail_input,
                output_schema={},
                allowed_phases=["DATA", "ORACLE"],
                source_system_id=SYSTEM_ID,
                provider_ref=DETAIL_ID,
            ),
            RuntimeFunctionDescriptor(
                function_id=DATABASE_ID,
                kind="mysql",
                description="扫描数据库只读查询",
                input_schema={"type": "object", "additionalProperties": True},
                output_schema={},
                allowed_phases=["ORACLE"],
                source_system_id=SYSTEM_ID,
                provider_ref=DATABASE_ID,
            ),
        ]
    )


def test_runtime_registry_accepts_scanned_operation_field_evidence() -> None:
    """验证真实扫描字段模型不会被误当成带业务身份标签的知识字段。

    Returns:
        None；断言只读Facade可以动态进入Runtime目录且不伪造身份输出路径。
    """

    # Operation扫描证据不包含business_identity；身份字段必须由后续显式DSL投影确定。
    capability = OperationCapability(
        operation_id=QUERY_LIST_ID,
        system_id=SYSTEM_ID,
        business_name="查询退票单列表",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        publication_output_schema={
            "type": "object",
            "properties": {
                "output": {
                    "type": "object",
                    "properties": {"refundSerialNo": {"type": "string"}},
                    "additionalProperties": False,
                }
            },
            "additionalProperties": False,
        },
        output_fields=[
            OperationFieldEvidence(
                field_path="refundSerialNo",
                field_name="refundSerialNo",
                declared_type="String",
            )
        ],
        provider_kind=OperationProviderKind.DSF_PROXY,
        provider_operation_id="dsf:refund:queryList",
        source_scan_id=SCAN_ID,
        executable=True,
    )

    registry = CaseTemplateRegistryLoader().runtime_registry(
        SYSTEM_ID,
        {SYSTEM_ID},
        [capability],
    )

    assert len(registry.functions) == 1
    assert registry.functions[0].function_id == QUERY_LIST_ID
    assert registry.functions[0].identity_output_paths == []


def test_source_search_glob_matches_root_and_nested_java_files(tmp_path: Path) -> None:
    """确认``*.java``与``**/*.java``都能搜索源码根和嵌套相对路径。

    Args:
        tmp_path: Pytest提供的隔离源码与审计目录。

    Returns:
        None；两种glob均命中两个Java文件时通过。
    """

    source_root = tmp_path / "source"
    nested_root = source_root / "app" / "src"
    # 同一标记分别放在源码根和嵌套目录，直接验证``**/``零层及多层语义。
    nested_root.mkdir(parents=True)
    (source_root / "Root.java").write_text("class Root { String marker; }", encoding="utf-8")
    (nested_root / "Nested.java").write_text("class Nested { String marker; }", encoding="utf-8")
    reader = RegisteredSourceReader(source_root, tmp_path / "source-audit.jsonl")

    basename_matches = reader.search_source("marker", file_glob="*.java")
    recursive_matches = reader.search_source("marker", file_glob="**/*.java")

    assert {item["path"] for item in basename_matches["matches"]} == {
        "Root.java",
        "app/src/Nested.java",
    }
    assert {item["path"] for item in recursive_matches["matches"]} == {
        "Root.java",
        "app/src/Nested.java",
    }


def test_v4_source_tool_reads_frozen_commit_snapshot_after_working_tree_changes(
    tmp_path: Path,
) -> None:
    """V4源码工具应始终读取handoff冻结快照而忽略working tree并发修改。

    Args:
        tmp_path: pytest隔离的注册源码、快照、审计和handoff目录。

    Returns:
        None；搜索只命中commit快照内容且不重新捕获活动源码时通过。

    Side Effects:
        在临时知识根创建一个模拟commit快照和源码访问审计文件。
    """

    # 先提交Codex本轮必须读取的源码，再由真实Git适配器发布受控快照。
    live_source = tmp_path / "live-refund-core"
    live_source.mkdir()
    subprocess.run(["git", "-C", str(live_source), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(live_source), "config", "user.email", "opentest@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(live_source), "config", "user.name", "OpenTest"],
        check=True,
    )
    source_file = live_source / "RefundFacade.java"
    source_file.write_text(
        "interface RefundFacade { String fixedCommitMarker; }\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(live_source), "add", "RefundFacade.java"], check=True)
    subprocess.run(
        ["git", "-C", str(live_source), "commit", "-q", "-m", "fixed source"],
        check=True,
    )
    artifacts = SourceScanArtifactStore(tmp_path / "knowledge")
    source_repository = GitSourceRepository()
    baseline = source_repository.capture_revision(live_source)
    commit = baseline.commit
    snapshot_path = artifacts.source_snapshot_path(SYSTEM_ID, commit)
    source_repository.materialize_revision(
        baseline,
        snapshot_path,
        artifacts.source_snapshot_root,
    )
    # 快照发布后制造并发working tree变化，handoff仍应保持原commit语义。
    source_file.write_text(
        "interface RefundFacade { String workingTreeChange; }\n",
        encoding="utf-8",
    )
    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'c' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(
                    source_path=str(live_source),
                    commit=commit,
                    revision="HEAD",
                    snapshot_path=str(snapshot_path),
                ),
            )
        ],
    )
    handoffs = Mock()
    handoffs.get.return_value = handoff
    handoffs.audit_path.return_value = tmp_path / "source-audit.jsonl"
    service = CaseTemplateV4Service(Mock(), artifacts, Mock(), handoffs)
    service.source_repository = source_repository

    response = service.call_source_tool(
        handoff.handoff_id,
        SYSTEM_ID,
        "search_source",
        {"pattern": "fixedCommitMarker", "file_glob": "*.java"},
    )

    assert [item["path"] for item in response["matches"]] == ["RefundFacade.java"]


def test_runtime_registry_adds_source_required_fields_and_initializer_defaults() -> None:
    """确认Runtime输入Schema区分可省略默认分页值和无默认必填平台ID。

    Returns:
        None；page/pageSize保留required与default，platFormId仅required时通过。
    """

    # 三个字段都带@required，但只有分页字段拥有可安全省略的Java初始化值。
    capability = OperationCapability(
        operation_id=QUERY_LIST_ID,
        system_id=SYSTEM_ID,
        business_name="查询退票单列表",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "pageSize": {"type": "integer"},
                "platFormId": {"type": "string"},
            },
            "additionalProperties": False,
        },
        input_fields=[
            OperationFieldEvidence(
                field_path="page",
                field_name="page",
                declared_type="int",
                documentation_required=True,
                has_declared_initializer=True,
                declared_initializer=1,
            ),
            OperationFieldEvidence(
                field_path="pageSize",
                field_name="pageSize",
                declared_type="int",
                documentation_required=True,
                has_declared_initializer=True,
                declared_initializer=20,
            ),
            OperationFieldEvidence(
                field_path="platFormId",
                field_name="platFormId",
                declared_type="String",
                documentation_required=True,
            ),
        ],
        provider_kind=OperationProviderKind.DSF_PROXY,
        provider_operation_id="dsf:refund:queryList",
        source_scan_id=SCAN_ID,
        executable=True,
    )

    registry = CaseTemplateRegistryLoader().runtime_registry(
        SYSTEM_ID,
        {SYSTEM_ID},
        [capability],
    )
    schema = registry.functions[0].input_schema

    assert schema["required"] == ["page", "pageSize", "platFormId"]
    assert schema["properties"]["page"]["default"] == 1
    assert schema["properties"]["pageSize"]["default"] == 20
    assert "default" not in schema["properties"]["platFormId"]


def test_outer_dsf_info_resolves_authorized_provider_facade_contract() -> None:
    """确认consumer外部索引按Java Facade符号解析booking provider真实契约。

    Returns:
        None；返回canonical provider、默认请求Schema、响应字段和源码范围时通过。
    """

    # consumer只提供外部索引身份，provider才拥有可执行Schema和canonical Operation。
    outer_id = "dsf:iflightchainsaas.booking.core:trade:queryList"
    facade_symbol = "com.ly.flight.chainsaas.booking.facade.TradeFacade#queryList"
    consumer = OperationCapability(
        operation_id=outer_id,
        system_id=SYSTEM_ID,
        business_name=f"{facade_symbol} · 外部DSF",
        kind=OperationKind.EXTERNAL_DSF,
        mutability=OperationMutability.READ_ONLY,
        source_symbol_refs=[
            SourceReference(path="BookOrderClient.java", symbol=facade_symbol, line=30)
        ],
        provider_kind=OperationProviderKind.EXTERNAL_DSF_PROXY,
        provider_operation_id=outer_id,
        source_scan_id=SCAN_ID,
        executable=True,
    )
    provider = OperationCapability(
        operation_id=TRADE_QUERY_LIST_ID,
        system_id=BOOKING_SYSTEM_ID,
        business_name="查询订单列表",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema={
            "type": "object",
            "properties": {"page": {"type": "integer"}},
            "additionalProperties": False,
        },
        publication_output_schema={
            "type": "object",
            "properties": {
                "output": {
                    "type": "object",
                    "properties": {"ownerId": {"type": "string"}},
                }
            },
        },
        input_fields=[
            OperationFieldEvidence(
                field_path="page",
                field_name="page",
                declared_type="int",
                documentation_required=True,
                has_declared_initializer=True,
                declared_initializer=1,
            )
        ],
        output_fields=[
            OperationFieldEvidence(
                field_path="ownerId",
                field_name="ownerId",
                declared_type="String",
            )
        ],
        source_symbol_refs=[
            SourceReference(path="TradeFacade.java", symbol=facade_symbol, line=26)
        ],
        provider_kind=OperationProviderKind.DSF_PROXY,
        provider_operation_id="dsf:booking:trade:queryList",
        source_scan_id="scan-booking-v4",
        executable=True,
    )
    handoffs = Mock()
    handoffs.get.return_value = Mock()
    service = CaseTemplateV4Service(Mock(), Mock(), Mock(), handoffs)
    service._runtime_capabilities = Mock(return_value=[consumer, provider])

    info = service.read_outer_api_info("case-template-handoff-" + "a" * 20, outer_id)

    assert info["provider_operation_id"] == TRADE_QUERY_LIST_ID
    assert info["provider_system_id"] == BOOKING_SYSTEM_ID
    assert info["request_schema"]["properties"]["page"]["default"] == 1
    assert info["response_fields"][0]["field_path"] == "ownerId"
    assert info["runtime_function"]["provider_ref"] == TRADE_QUERY_LIST_ID
    assert info["provider_source_refs"][0]["path"] == "TradeFacade.java"
    handoffs.record_outer_provider_access.assert_called_once_with(
        "case-template-handoff-" + "a" * 20,
        outer_id,
        TRADE_QUERY_LIST_ID,
    )


def _compile_golden() -> tuple[list, list]:
    """使用固定目录编译cancel Golden。

    Returns:
        五个Variant和问题列表。
    """

    compilation = CaseTemplateCompilationInput(
        submission=_golden_submission(),
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
            "required": ["success", "orderSerialNo"],
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )
    return CaseTemplateCompilerV4().compile(compilation)


class _FakeOperationService:
    """模拟统一Operation服务并记录V4是否通用派发所有阶段。"""

    def __init__(self):
        """初始化调用记录。"""

        self.calls: list[tuple[str, object]] = []

    def execute(self, system_id: str, request: object) -> OperationExecutionRecord:
        """按Operation ID返回可预测的query、cancel、detail或数据库业务结果。

        Args:
            system_id: Operation目录所属系统。
            request: 统一OperationExecutionRequest。

        Returns:
            COMPLETED记录及与请求动态身份一致的业务响应。
        """

        self.calls.append((system_id, request))
        operation_id = request.operation_id
        arguments = request.arguments
        state_names = {0: "PENDING_APPLY", 1: "AUDITED", 2: "WAIT_REFUND", 5: "REFUND_FAIL", 8: "RESHOPING"}
        # 两段DATA链必须先得到真实ownerId，再带同一个值查询退票单。
        if operation_id == TRADE_QUERY_LIST_ID:
            business = {
                "success": True,
                "list": {"pageList": [{"ownerId": "OWNER-100"}]},
            }
        elif operation_id == QUERY_LIST_ID and "orderState" in arguments:
            state = arguments["orderState"]
            assert arguments["platFormId"] == "OWNER-100"
            business = {
                "success": True,
                "list": {"pageList": [{"refundSerialNo": f"RF-{state}", "refundState": state_names[state]}]},
            }
        elif operation_id == CANCEL_ID:
            business = {"success": True, "orderSerialNo": arguments["refundSerialNo"]}
        elif operation_id == DETAIL_ID:
            business = {"success": True, "saasRefundOrderVO": {"refundState": "REFUND_CANCEL"}}
        elif operation_id == DATABASE_ID:
            business = {
                "rows": [
                    {
                        "refund_state": 6,
                        "cancel_reason": "OPENTEST_CANCEL",
                        "cancel_remark": "OpenTest V4 Golden Case",
                        "operator": "opentest-v4",
                    }
                ],
                "row_count": 1,
            }
        else:
            business = {"success": True, "list": {"pageList": []}}
        result = business if operation_id == DATABASE_ID else {"status": "success", "output": business}
        identity = str(len(self.calls)).rjust(20, "a")
        return OperationExecutionRecord(
            execution_id=f"operation-execution-{identity}",
            request_id=request.request_id,
            request_digest="a" * 64,
            system_id=system_id,
            operation_id=operation_id,
            kind=OperationKind.DATABASE if operation_id == DATABASE_ID else OperationKind.FACADE,
            status=OperationExecutionStatus.COMPLETED,
            result=result,
        )


class _EmptyBookingOperationService(_FakeOperationService):
    """模拟booking查询成功但当前QA没有可用于提取ownerId的订单。"""

    def execute(self, system_id: str, request: object) -> OperationExecutionRecord:
        """保留真实booking Operation记录并把业务列表替换为空集合。

        Args:
            system_id: Operation目录所属系统。
            request: 统一OperationExecutionRequest。

        Returns:
            booking查询为成功空列表，其余Operation沿用完整成功替身。
        """

        record = super().execute(system_id, request)
        if request.operation_id != TRADE_QUERY_LIST_ID:
            return record
        # 空集合仍是一次已完成的真实数据准备调用，用于验证BLOCKED轨迹不会丢失。
        return record.model_copy(
            update={
                "result": {
                    "status": "success",
                    "output": {"success": True, "list": {"pageList": []}},
                }
            }
        )


class _FailedBookingOperationService(_FakeOperationService):
    """模拟booking Provider已经执行但返回失败终态。"""

    def execute(self, system_id: str, request: object) -> OperationExecutionRecord:
        """把首个booking执行记录转换为Provider失败。

        Args:
            system_id: Operation目录所属系统。
            request: 统一OperationExecutionRequest。

        Returns:
            带真实execution ID、失败状态和安全错误信息的Operation记录。
        """

        record = super().execute(system_id, request)
        if request.operation_id != TRADE_QUERY_LIST_ID:
            return record
        # Provider失败与成功空集合语义不同，执行器必须返回FAILED而不是BLOCKED。
        return record.model_copy(
            update={
                "status": OperationExecutionStatus.FAILED,
                "message": "booking QA provider failed",
                "error_code": "QA_PROVIDER_FAILED",
            }
        )


def test_typed_value_sources_reject_legacy_free_string_references() -> None:
    """确认旧source/reference和模糊data output均无法进入V4模型。"""

    with pytest.raises(ValidationError):
        DslValueSource.model_validate({"source": "data_output", "reference": "candidate.refundSerialNo"})
    with pytest.raises(ValidationError, match="incomplete or ambiguous"):
        DslValueSource(kind="data_output", call_id="candidate")
    source = DslValueSource(kind="data_output", call_id="candidate", output_name="refund_serial_no")
    assert source.call_id == "candidate"
    assert source.output_name == "refund_serial_no"


def test_golden_project_and_oracles_are_fully_machine_executable() -> None:
    """确认Golden没有键值自映射、自由引用或无证据Redis/MQ Oracle。"""

    submission = _golden_submission()
    booking_projection = submission.data_functions[0].steps[-1]
    refund_projection = submission.data_functions[1].steps[-1]
    oracle_channels = {oracle.channel for oracle in submission.case_templates[0].oracles}

    assert [(item.output_name, item.source_path) for item in booking_projection.fields] == [
        ("owner_id", "ownerId"),
    ]
    assert [(item.output_name, item.source_path) for item in refund_projection.fields] == [
        ("refund_serial_no", "refundSerialNo"),
        ("refund_state_name", "refundState"),
    ]
    assert oracle_channels == {"response", "operation", "mysql"}
    assert "candidate.refundSerialNo" not in GOLDEN_PATH.read_text(encoding="utf-8")


def test_cancel_golden_compiles_exactly_five_code_name_variants() -> None:
    """确认五个源码枚举code/name分别形成一个可执行Variant。"""

    variants, issues = _compile_golden()

    assert issues == []
    assert len(variants) == 5
    assert [item.parameter_values["cancellable_state"] for item in variants] == [
        {"code": 0, "name": "PENDING_APPLY"},
        {"code": 1, "name": "AUDITED"},
        {"code": 2, "name": "WAIT_REFUND"},
        {"code": 5, "name": "REFUND_FAIL"},
        {"code": 8, "name": "RESHOPING"},
    ]
    assert all(item.request_values["refundSerialNo"]["kind"] == "data_output" for item in variants)


def test_business_identity_requires_dynamic_data_output() -> None:
    """确认business和state模板不能用字面量或随机参数伪造业务身份。

    Returns:
        None；refundSerialNo改为字面量后模板被精确阻塞时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    bindings = [
        binding.model_copy(update={"source": DslValueSource(kind="literal", value="RF-FAKE")})
        if binding.field == "refundSerialNo"
        else binding
        for binding in template.request_bindings
    ]
    invalid_submission = submission.model_copy(
        update={"case_templates": [template.model_copy(update={"request_bindings": bindings})]}
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "BUSINESS_IDENTITY_SOURCE_FORBIDDEN" in {item.code for item in issues}


def test_data_seed_rejects_literal_hidden_behind_function_input() -> None:
    """确认无默认必填platFormId不能通过data function输入包装伪造字面量。

    Returns:
        None；编译在QA前返回UNTRUSTED_DATA_SEED且不生成Variant时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    # 仅替换跨函数platform_id来源，保留其余Golden步骤以定位seed校验本身。
    refund_call = template.data_calls[1].model_copy(
        update={
            "arguments": {
                **template.data_calls[1].arguments,
                "platform_id": DslValueSource(kind="literal", value="1"),
            }
        }
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"data_calls": [template.data_calls[0], refund_call]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "UNTRUSTED_DATA_SEED" in {item.code for item in issues}


def test_dynamic_data_output_type_is_checked_before_qa() -> None:
    """确认跨函数data output类型不兼容时在编译期阻塞。

    Returns:
        None；booking ownerId被伪造为整数Schema时产生类型问题即通过。
    """

    submission = _golden_submission()
    booking_function = submission.data_functions[0]
    invalid_output_schema = deepcopy(booking_function.steps[0].output_schema)
    owner_schema = invalid_output_schema["properties"]["list"]["properties"]["pageList"]["items"]["properties"]
    owner_schema["ownerId"] = {"type": "integer"}
    invalid_step = booking_function.steps[0].model_copy(
        update={"output_schema": invalid_output_schema}
    )
    invalid_function = booking_function.model_copy(
        update={"steps": [invalid_step, *booking_function.steps[1:]]}
    )
    invalid = submission.model_copy(
        update={"data_functions": [invalid_function, submission.data_functions[1]]}
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issue_codes = {item.code for item in CaseTemplateValidatorV4().validate(compilation)}

    assert "DATA_CALL_ARGUMENT_TYPE_MISMATCH" in issue_codes


def test_business_template_rejects_generic_boundary_matrix() -> None:
    """确认business模板不能把普通字符串边界扩展成统一成功Case。

    Returns:
        None；string.boundary被编译器在QA前精确阻塞时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    # 把唯一业务状态维度替换为通用字符串边界，模拟此前错误的成功矩阵。
    boundary_parameter = template.parameters[0].model_copy(
        update={
            "function_id": "string.boundary",
            "arguments": {"min_length": 1, "max_length": 20},
        }
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(update={"parameters": [boundary_parameter]})
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "BUSINESS_VALUE_FUNCTION_FORBIDDEN" in {item.code for item in issues}


def test_variant_identity_reuses_target_when_only_oracle_changes() -> None:
    """确认同一handoff只修订Oracle时复用目标写调用而重新判定断言。

    Returns:
        None；相同目标请求与数据准备语义保持同一Variant ID时通过。
    """

    original_variants, original_issues = _compile_golden()
    submission = _golden_submission()
    template = submission.case_templates[0]
    response_oracle = template.oracles[0]
    changed_assertion = response_oracle.assertions[0].model_copy(
        update={"expected": DslValueSource(kind="literal", value=False)}
    )
    changed_oracle = response_oracle.model_copy(update={"assertions": [changed_assertion]})
    changed_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(update={"oracles": [changed_oracle, *template.oracles[1:]]})
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=changed_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    changed_variants, changed_issues = CaseTemplateCompilerV4().compile(compilation)

    assert original_issues == []
    assert changed_issues == []
    assert original_variants[0].parameter_values == changed_variants[0].parameter_values
    assert original_variants[0].variant_id == changed_variants[0].variant_id


def test_value_functions_cover_enum_pairs_collection_and_typed_nullability() -> None:
    """确认新增集合边界和类型感知空值，同时严格校验枚举code/name。"""

    engine = ValueFunctionEngine()
    pairs = [{"code": 0, "name": "PENDING"}, {"code": 1, "name": "DONE"}]

    assert engine.generate("enum.values", {"values": pairs}, {}, __import__("random").Random(1)) == pairs
    assert engine.generate(
        "collection.size_boundary",
        {"min_size": 1, "max_size": 2, "item": "x"},
        {"type": "array"},
        __import__("random").Random(1),
    ) == [[], ["x"], ["x", "x"], ["x", "x", "x"]]
    nullable = engine.generate(
        "nullability.all",
        {"include_omit": True},
        {"type": "string"},
        __import__("random").Random(1),
        "normal",
    )
    assert nullable == ["normal", "", None, {"$omit": True}]
    with pytest.raises(KnowledgeValidationError, match="code/name"):
        engine.generate(
            "enum.values",
            {"values": [{"code": 0}, {"code": 1, "name": "DONE"}]},
            {},
            __import__("random").Random(1),
        )


def test_enum_pair_request_binding_requires_explicit_member_path() -> None:
    """确认code/name配对对象不能整体写入标量请求字段。

    Returns:
        None；直接绑定类型不兼容而选择code成员可通过时通过。
    """

    validator = CaseTemplateValidatorV4()
    parameter = _golden_submission().case_templates[0].parameters[0]
    request_schema = {
        "type": "object",
        "properties": {"refundState": {"type": "integer"}},
        "additionalProperties": False,
    }
    parameters = {parameter.name: parameter}

    # 参数保留code/name配对供不同阶段使用，请求绑定必须显式投影目标标量成员。
    pair_schema = validator._template_source_schema(
        DslValueSource(kind="parameter", name=parameter.name),
        parameters,
        request_schema,
    )
    code_schema = validator._template_source_schema(
        DslValueSource(kind="parameter", name=parameter.name, path="code"),
        parameters,
        request_schema,
    )

    # 完整Validator还必须把整体对象绑定到refundSerialNo字符串识别为模板级编译问题。
    submission = _golden_submission()
    template = submission.case_templates[0]
    invalid_binding = template.request_bindings[0].model_copy(
        update={"source": DslValueSource(kind="parameter", name=parameter.name)}
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"request_bindings": [invalid_binding, *template.request_bindings[1:]]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )
    issues = validator.validate(compilation)

    assert not validator._schemas_compatible(pair_schema or {}, {"type": "integer"})
    assert validator._schemas_compatible(code_schema or {}, {"type": "integer"})
    assert "REQUEST_BINDING_TYPE_MISMATCH" in {issue.code for issue in issues}


def test_enum_code_name_pairs_must_match_one_source_declaration() -> None:
    """确认真实枚举name不能包装错误code通过源码证据校验。

    Returns:
        None；正确五组code/name通过而修改任一code后产生稳定问题码时通过。
    """

    submission = _golden_submission()
    enum_path = submission.data_functions[1].evidence[-1].path
    enum_source = """
        enum RefundOrderStateEnum {
            PENDING_APPLY(0, "退票申请"), AUDITED(1, "审核通过"),
            WAIT_REFUND(2, "待退票"), REFUND_FAIL(5, "退票失败"),
            RESHOPING(8, "核价中");
        }
    """
    base = CaseTemplateCompilationInput(
        submission=submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
        source_text_by_system_path={SYSTEM_ID: {enum_path: enum_source}},
    )
    valid_codes = {item.code for item in CaseTemplateValidatorV4().validate(base)}
    template = submission.case_templates[0]
    invalid_parameter = template.parameters[0].model_copy(
        update={
            "arguments": {
                "values": [
                    {"code": 99, "name": "PENDING_APPLY"},
                    *template.parameters[0].arguments["values"][1:],
                ]
            }
        }
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(update={"parameters": [invalid_parameter]})
            ]
        }
    )
    invalid_codes = {
        item.code
        for item in CaseTemplateValidatorV4().validate(
            base.model_copy(update={"submission": invalid_submission})
        )
    }

    assert "ENUM_VALUES_SOURCE_UNPROVEN" not in valid_codes
    assert "ENUM_VALUES_SOURCE_UNPROVEN" in invalid_codes


def test_runtime_registry_is_derived_from_operations_without_refund_fixture() -> None:
    """确认Runtime Function来自扫描Operation而不是静态refund/MySQL/Redis/MQ写死目录。

    Returns:
        None；目录仅包含可作为运行函数使用的Facade与数据库Operation时通过。
    """

    facade = OperationCapability(
        operation_id="facade:sample.QueryFacade#search",
        system_id=SYSTEM_ID,
        business_name="查询样例",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        publication_output_schema={
            "type": "object",
            "properties": {"output": {"type": "object", "properties": {"success": {"type": "boolean"}}}},
        },
        source_scan_id=SCAN_ID,
        executable=True,
    )
    database = OperationCapability(
        operation_id=DATABASE_ID,
        system_id=SYSTEM_ID,
        business_name="退款数据库",
        kind=OperationKind.DATABASE,
        mutability=OperationMutability.WRITE,
        input_schema={},
        source_scan_id=SCAN_ID,
        executable=True,
    )
    mq_sender = OperationCapability(
        operation_id="mq:sample-system:sample-consumer",
        system_id=SYSTEM_ID,
        business_name="向样例消费者发送消息",
        kind=OperationKind.MQ,
        mutability=OperationMutability.WRITE,
        input_schema={
            "type": "object",
            "properties": {"message": {}},
            "required": ["message"],
            "additionalProperties": False,
        },
        source_scan_id=SCAN_ID,
        executable=True,
    )

    # MQ目录当前是写入消费者的测试激励，不能被投影成只读结果Observer。
    registry = CaseTemplateRegistryLoader().runtime_registry(
        SYSTEM_ID,
        {SYSTEM_ID},
        [facade, database, mq_sender],
    )

    assert {item.function_id for item in registry.functions} == {facade.operation_id, DATABASE_ID}
    assert {item.kind for item in registry.functions} == {"dsf", "mysql"}
    assert all("refund_order.get" not in item.function_id for item in registry.functions)


@pytest.mark.parametrize(
    ("channel", "function_id", "statement"),
    [
        ("redis", "redis:sample-system:sample-cache", "GET"),
        ("mq", "mq:sample-system:sample-consumer", "OBSERVE"),
    ],
)
def test_v4_blocks_resource_oracles_without_authorized_observer(
    channel: str,
    function_id: str,
    statement: str,
) -> None:
    """确认Redis或MQ只有进入Runtime目录的只读Observer才能用于V4断言。

    Args:
        channel: 待验证的资源Oracle通道。
        function_id: 未获授权的资源函数ID。
        statement: 资源观察命令占位值。

    Returns:
        None；校验器返回UNKNOWN_ORACLE_FUNCTION时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    mysql = template.oracles[-1]
    resource_oracle = mysql.model_copy(
        update={
            "oracle_id": f"{channel}.unauthorized_observer",
            "channel": channel,
            "function_id": function_id,
            "statement": statement,
        }
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"oracles": [*template.oracles[:-1], resource_oracle]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert "UNKNOWN_ORACLE_FUNCTION" in {item.code for item in issues}


def test_v4_catalog_runtime_scope_keeps_same_facade_and_controlled_database() -> None:
    """确认首轮目录不会把其他Facade和第三方完整契约一次性发送给AI。

    Returns:
        None；仅同Facade旁路接口和本系统数据库进入首轮Runtime目录时通过。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'b' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
    )
    same_facade = Mock(
        system_id=SYSTEM_ID,
        operation_id=QUERY_LIST_ID,
        kind=OperationKind.FACADE,
    )
    target = Mock(
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        kind=OperationKind.FACADE,
    )
    other_facade = Mock(
        system_id=SYSTEM_ID,
        operation_id="facade:com.example.OtherFacade#query",
        kind=OperationKind.FACADE,
    )
    database = Mock(
        system_id=SYSTEM_ID,
        operation_id=DATABASE_ID,
        kind=OperationKind.DATABASE,
    )
    outer = Mock(
        system_id=SYSTEM_ID,
        operation_id="dsf:booking:trade:queryDetail",
        kind=OperationKind.EXTERNAL_DSF,
    )

    selected = CaseTemplateV4Service(Mock(), Mock(), Mock(), Mock())._catalog_runtime_capabilities(
        handoff,
        [target, same_facade, other_facade, database, outer],
    )

    assert [item.operation_id for item in selected] == [QUERY_LIST_ID, DATABASE_ID]


def test_submit_runtime_scope_requires_outer_api_access_audit(tmp_path: Path) -> None:
    """确认submit只能使用首轮目录和按需展开过的第三方provider。

    Args:
        tmp_path: pytest提供的隔离私有状态目录。

    Returns:
        None；未展开时provider不可见，记录工具审计后才进入Runtime范围。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'3' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
    )
    same_facade = Mock(
        system_id=SYSTEM_ID,
        operation_id=QUERY_LIST_ID,
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
    )
    target = Mock(
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        kind=OperationKind.FACADE,
        mutability=OperationMutability.WRITE,
    )
    provider = Mock(
        system_id=BOOKING_SYSTEM_ID,
        operation_id=TRADE_QUERY_LIST_ID,
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
    )
    handoff_store = CaseTemplateHandoffStoreV4(tmp_path)
    service = CaseTemplateV4Service(Mock(), Mock(), Mock(), handoff_store)

    before = service._submission_runtime_capabilities(
        handoff,
        [target, same_facade, provider],
    )
    handoff_store.record_outer_provider_access(
        handoff.handoff_id,
        "dsf:booking:trade:queryList",
        TRADE_QUERY_LIST_ID,
    )
    after = service._submission_runtime_capabilities(
        handoff,
        [target, same_facade, provider],
    )

    assert [item.operation_id for item in before] == [QUERY_LIST_ID]
    assert [item.operation_id for item in after] == [TRADE_QUERY_LIST_ID, QUERY_LIST_ID]


def test_mysql_observer_rejects_writes_and_parameter_mismatch() -> None:
    """确认MySQL Observer只能使用单条命名参数SELECT。"""

    submission = _golden_submission()
    template = submission.case_templates[0]
    mysql = template.oracles[-1].model_copy(
        update={"statement": "UPDATE saas_refund_order SET refund_state = 6"}
    )
    unsafe = submission.model_copy(
        update={"case_templates": [template.model_copy(update={"oracles": [*template.oracles[:-1], mysql]})]}
    )
    compilation = CaseTemplateCompilationInput(
        submission=unsafe,
        input_contract=_cancel_contract(),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}}},
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert {item.code for item in issues} >= {"UNSAFE_MYSQL_OBSERVER", "MYSQL_PARAMETER_MISMATCH"}


def test_mysql_observer_accepts_camel_case_named_parameters() -> None:
    """确认MySQL命名参数可与Java请求字段一致使用camelCase。

    Returns:
        None；占位符与arguments逐字一致时不产生参数不匹配问题。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    mysql = template.oracles[-1]
    arguments = dict(mysql.arguments)
    refund_source = arguments.pop("refund_serial_no")
    camel_mysql = mysql.model_copy(
        update={
            "statement": mysql.statement.replace(":refund_serial_no", ":refundSerialNo"),
            "arguments": {"refundSerialNo": refund_source, **arguments},
        }
    )
    camel_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"oracles": [*template.oracles[:-1], camel_mysql]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=camel_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "orderSerialNo": {"type": "string"},
            },
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert "MYSQL_PARAMETER_MISMATCH" not in {item.code for item in issues}


@pytest.mark.parametrize(
    ("statement", "expected_code"),
    [
        (
            "SELECT LOAD_FILE('/etc/passwd') FROM saas_refund_order LIMIT 1",
            "UNSAFE_MYSQL_OBSERVER",
        ),
        (
            "SELECT refund_state FROM saas_refund_order INTO DUMPFILE '/tmp/x' LIMIT 1",
            "UNSAFE_MYSQL_OBSERVER",
        ),
        (
            "SELECT refund_state FROM other_schema.saas_refund_order LIMIT 1",
            "MYSQL_RESOURCE_SCOPE_UNPROVEN",
        ),
        (
            "SELECT 1 FROM saas_refund_order LIMIT 1",
            "MYSQL_PROJECTION_UNSAFE",
        ),
        (
            "SELECT refund_state FROM saas_refund_order WHERE GET_LOCK('v4', 300) = 1 LIMIT 1",
            "UNSAFE_MYSQL_OBSERVER",
        ),
    ],
)
def test_mysql_observer_rejects_file_access_cross_schema_and_constant_projection(
    statement: str,
    expected_code: str,
) -> None:
    """确认Observer在访问QA前拒绝文件函数、跨库表和常量伪造投影。

    Args:
        statement: 待验证的恶意或无证据SQL。
        expected_code: 对应确定性阻塞码。

    Returns:
        None；目标阻塞码出现时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    mysql = template.oracles[-1].model_copy(update={"statement": statement, "arguments": {}})
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(update={"oracles": [*template.oracles[:-1], mysql]})
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert expected_code in {item.code for item in issues}


def test_mysql_observer_requires_table_and_projection_in_read_source_evidence() -> None:
    """确认MySQL表和投影字段必须能在当前Oracle已读源码内容中证明。

    Returns:
        None；真实DO字段通过而虚构源码内容被阻塞时通过。
    """

    submission = _golden_submission()
    mysql = submission.case_templates[0].oracles[-1]
    invoker_path = mysql.evidence[0].path
    data_object_path = mysql.evidence[-1].path
    compilation = CaseTemplateCompilationInput(
        submission=submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
        source_text_by_system_path={
            SYSTEM_ID: {
                invoker_path: "class RefundCancelServiceInvoker { void doInvoke() {} }",
                data_object_path: (
                    "// saas_refund_order\n"
                    "class SaasRefundOrderDO { private Integer refundState; private String cancelReason; "
                    "private String cancelRemark; private String operator;"
                )
            }
        },
    )

    valid_codes = {item.code for item in CaseTemplateValidatorV4().validate(compilation)}
    fabricated = compilation.model_copy(
        update={
            "source_text_by_system_path": {
                SYSTEM_ID: {
                    invoker_path: "class UnrelatedService {}",
                    data_object_path: "class UnrelatedRecord {}",
                }
            }
        }
    )
    fabricated_codes = {item.code for item in CaseTemplateValidatorV4().validate(fabricated)}

    assert "MYSQL_SOURCE_EVIDENCE_UNPROVEN" not in valid_codes
    assert "MYSQL_SOURCE_EVIDENCE_UNPROVEN" in fabricated_codes


def test_evidence_line_must_belong_to_read_source_range() -> None:
    """确认源码证据行号不能指向Codex没有读取的文件区间。

    Returns:
        None；把真实symbol行改到已读区间外后产生稳定阻塞码时通过。
    """

    submission = _golden_submission()
    function = submission.data_functions[0]
    invalid_evidence = function.evidence[0].model_copy(update={"line": 999})
    invalid_submission = submission.model_copy(
        update={
            "data_functions": [
                function.model_copy(update={"evidence": [invalid_evidence, *function.evidence[1:]]})
            ]
        }
    )
    paths = {
        evidence.path
        for evidence in [
            *(item for draft in invalid_submission.data_functions for item in draft.evidence),
            *(item for template in invalid_submission.case_templates for item in template.evidence),
            *(
                item
                for template in invalid_submission.case_templates
                for oracle in template.oracles
                for item in oracle.evidence
            ),
        ]
    }
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
        accessed_paths_by_system={SYSTEM_ID: paths},
        accessed_ranges_by_system_path={
            SYSTEM_ID: {path: [(1, 400)] for path in paths}
        },
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert "EVIDENCE_LINE_NOT_READ" in {item.code for item in issues}


def test_evidence_symbol_must_appear_on_declared_audited_line() -> None:
    """确认同一已读文件另一行的symbol不能替声明行提供证据。

    Returns:
        None；symbol仅出现在不同审计行时产生EVIDENCE_SYMBOL_UNPROVEN。
    """

    submission = _golden_submission()
    evidence = submission.data_functions[0].evidence[0]
    compilation = CaseTemplateCompilationInput(
        submission=submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
        source_text_by_system_path={
            evidence.source_system_id: {
                evidence.path: (
                    f"{evidence.line}\tpublic interface UnrelatedFacade {{}}\n"
                    f"{(evidence.line or 1) + 4}\tRefundOrderListResponse queryList(Request request);"
                )
            }
        },
    )

    issues = CaseTemplateValidatorV4()._evidence_issues(
        compilation,
        "data_function:get_booking_owner_id",
        [evidence],
    )

    assert "EVIDENCE_SYMBOL_UNPROVEN" in {item.code for item in issues}


def test_operation_oracle_arguments_must_match_runtime_input_schema() -> None:
    """确认详情等Operation Oracle的额外参数会在访问QA前被阻塞。

    Returns:
        None；未知参数产生ORACLE_ARGUMENT_MISMATCH时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    operation_oracle = template.oracles[1]
    invalid_oracle = operation_oracle.model_copy(
        update={
            "arguments": {
                **operation_oracle.arguments,
                "unknown": DslValueSource(kind="literal", value="forbidden"),
            }
        }
    )
    invalid_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"oracles": [template.oracles[0], invalid_oracle, *template.oracles[2:]]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    issues = CaseTemplateValidatorV4().validate(compilation)

    assert "ORACLE_ARGUMENT_MISMATCH" in {item.code for item in issues}


def test_dynamic_value_function_base_source_returns_compilation_issue() -> None:
    """确认执行期数据不能作为编译期ValueFunction基线并触发服务异常。

    Returns:
        None；编译器返回可定位的VALUE_FUNCTION_ERROR且不抛TypeError时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    dynamic_parameter = template.parameters[0].model_copy(
        update={
            "name": "dynamic_nullable_refund_no",
            "target_field": "refundSerialNo",
                "function_id": "enum.values",
                "arguments": {"values": ["SOURCE_PROVEN_VALUE"]},
            "base_source": DslValueSource(
                kind="data_output",
                call_id="cancellable_refund_order",
                output_name="refund_serial_no",
            ),
        }
    )
    dynamic_submission = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"parameters": [*template.parameters, dynamic_parameter]}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=dynamic_submission,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "orderSerialNo": {"type": "string"},
            },
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert {item.code for item in issues} == {"VALUE_FUNCTION_ERROR"}


def test_response_and_observer_actual_paths_must_belong_to_schema() -> None:
    """确认Oracle不能用自然语言或不存在路径冒充可执行断言。"""

    submission = _golden_submission()
    template = submission.case_templates[0]
    response = template.oracles[0].model_copy(
        update={
            "assertions": [
                CaseOracleAssertion(
                    actual_path="业务应该取消成功",
                    operator="eq",
                    expected=DslValueSource(kind="literal", value=True),
                )
            ]
        }
    )
    invalid = submission.model_copy(
        update={"case_templates": [template.model_copy(update={"oracles": [response, *template.oracles[1:]]})]}
    )
    compilation = CaseTemplateCompilationInput(
        submission=invalid,
        input_contract=_cancel_contract(),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}}},
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    assert "INVALID_ORACLE_ACTUAL_PATH" in {item.code for item in CaseTemplateValidatorV4().validate(compilation)}


def test_variant_limit_blocks_without_truncating() -> None:
    """确认超过100个Variant时整体阻塞而不是静默取前100个。"""

    submission = _golden_submission()
    template = submission.case_templates[0]
    first = template.parameters[0].model_copy(
        update={
            "arguments": {
                "values": [
                    {"code": code, "name": f"STATE_{code}"}
                    for code in range(11)
                ]
            }
        }
    )
    second = first.model_copy(update={"name": "second_dimension"})
    oversized = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(
                    update={"parameters": [first, second], "combination": "cartesian"}
                )
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=oversized,
        input_contract=_cancel_contract(),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}}},
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "VARIANT_LIMIT_EXCEEDED" in {item.code for item in issues}


def test_cartesian_variant_limit_stops_before_materializing_the_full_product() -> None:
    """确认巨大笛卡尔积只检查前101个有效组合而不会完整物化。

    Returns:
        None；四个百值维度可快速返回整体超限问题时通过。
    """

    submission = _golden_submission()
    template = submission.case_templates[0]
    parameter = template.parameters[0]
    values = [{"code": code, "name": f"STATE_{code}"} for code in range(100)]
    dimensions = [
        parameter.model_copy(
            update={"name": parameter.name if index == 0 else f"dimension_{index}", "arguments": {"values": values}}
        )
        for index in range(4)
    ]
    oversized = submission.model_copy(
        update={
            "case_templates": [
                template.model_copy(update={"parameters": dimensions, "combination": "cartesian"})
            ]
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=oversized,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "VARIANT_LIMIT_EXCEEDED" in {item.code for item in issues}


def test_operation_limit_blocks_template_before_qa_execution() -> None:
    """确认单Variant超过100次Operation时在编译期精确阻塞模板。

    Returns:
        None；生成结果为空且包含OPERATION_LIMIT_EXCEEDED时通过。
    """

    submission = _golden_submission()
    function = submission.data_functions[0]
    runtime_step = function.steps[0]
    extra_runtime_steps = [
        runtime_step.model_copy(update={"step_id": f"query_orders_extra_{index}"})
        for index in range(17)
    ]
    expanded_function = function.model_copy(
        update={"steps": [runtime_step, *extra_runtime_steps, *function.steps[1:]]}
    )
    template = submission.case_templates[0]
    data_call = template.data_calls[0]
    expanded_calls = [
        data_call.model_copy(update={"call_id": f"cancellable_refund_order_{index}"})
        for index in range(6)
    ]
    oversized = submission.model_copy(
        update={
            "data_functions": [expanded_function],
            "case_templates": [template.model_copy(update={"data_calls": expanded_calls})],
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=oversized,
        input_contract=_cancel_contract(),
        target_output_schema={
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "orderSerialNo": {"type": "string"}},
        },
        runtime_registry=_runtime_registry(),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )

    variants, issues = CaseTemplateCompilerV4().compile(compilation)

    assert variants == []
    assert "OPERATION_LIMIT_EXCEEDED" in {item.code for item in issues}


def test_cancel_executor_runs_dynamic_data_target_detail_and_mysql() -> None:
    """确认五个cancel Variant逐次跨系统选单并保留五阶段execution ID和断言明细。

    Returns:
        None；五个Variant完成动态取数、目标调用和结构化Oracle执行时通过。
    """

    variants, issues = _compile_golden()
    generation = CaseTemplateGenerationV4(
        generation_id=f"case-template-generation-{'a' * 20}",
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{CANCEL_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_cancel_contract(),
        submission=_golden_submission(),
        issues=issues,
        variants=variants,
    )
    operations = _FakeOperationService()

    results = CaseTemplateExecutorV4(operations).execute(
        f"case-template-handoff-{'b' * 20}",
        generation,
        _runtime_registry(),
    )

    assert len(results) == 5
    assert {item.status for item in results} == {"COMPLETED"}
    assert [item.actual_request["refundSerialNo"] for item in results] == ["RF-0", "RF-1", "RF-2", "RF-5", "RF-8"]
    assert all(len(item.operations) == 5 for item in results)
    assert all(item.operations[0].function_id == TRADE_QUERY_LIST_ID for item in results)
    assert all(item.operations[0].request == {"page": 1, "pageSize": 20} for item in results)
    assert [item.operations[1].request for item in results] == [
        {"page": 1, "pageSize": 20, "platFormId": "OWNER-100", "orderState": state}
        for state in (0, 1, 2, 5, 8)
    ]
    # 数据库Worker只接受小写case用途；执行器必须发送协议值而不是DSL通道名称。
    database_requests = [
        operation.request
        for item in results
        for operation in item.operations
        if operation.function_id == DATABASE_ID
    ]
    assert database_requests
    assert all(request["purpose"] == "case" for request in database_requests)
    assert all(len(item.assertions) == 9 and all(assertion.passed for assertion in item.assertions) for item in results)
    assert all(operation.execution_id for item in results for operation in item.operations)


def test_blocked_data_call_preserves_completed_operation_request_and_response() -> None:
    """确认DATA后续选取失败时仍返回已执行第三方查询的完整轨迹。

    Returns:
        None；每个Variant为BLOCKED、目标请求为空且booking请求响应可见时通过。
    """

    variants, issues = _compile_golden()
    generation = CaseTemplateGenerationV4(
        generation_id=f"case-template-generation-{'f' * 20}",
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{CANCEL_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_cancel_contract(),
        submission=_golden_submission(),
        issues=issues,
        variants=variants,
    )

    # booking调用成功后first步骤因空集合BLOCKED，cancel及后续Oracle不得执行。
    results = CaseTemplateExecutorV4(_EmptyBookingOperationService()).execute(
        f"case-template-handoff-{'e' * 20}",
        generation,
        _runtime_registry(),
    )

    assert {item.status for item in results} == {"BLOCKED"}
    assert all(item.actual_request == {} for item in results)
    assert all(len(item.operations) == 1 for item in results)
    assert all(item.operations[0].function_id == TRADE_QUERY_LIST_ID for item in results)
    assert all(item.operations[0].request == {"page": 1, "pageSize": 20} for item in results)
    assert all(item.operations[0].response["list"]["pageList"] == [] for item in results)


def test_provider_failure_is_failed_and_preserves_operation_trace() -> None:
    """确认QA Provider失败不会被误报为动态数据BLOCKED。

    Returns:
        None；全部Variant为FAILED且保留失败booking execution时通过。
    """

    variants, issues = _compile_golden()
    generation = CaseTemplateGenerationV4(
        generation_id=f"case-template-generation-{'1' * 20}",
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{CANCEL_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_cancel_contract(),
        submission=_golden_submission(),
        issues=issues,
        variants=variants,
    )

    results = CaseTemplateExecutorV4(_FailedBookingOperationService()).execute(
        f"case-template-handoff-{'2' * 20}",
        generation,
        _runtime_registry(),
    )

    assert {item.status for item in results} == {"FAILED"}
    assert all(len(item.operations) == 1 for item in results)
    assert all(item.operations[0].status == "FAILED" for item in results)
    assert all(item.operations[0].execution_id for item in results)
    assert all("booking QA provider failed" in item.error for item in results)


def test_operation_request_identity_is_stable_and_binds_actual_arguments() -> None:
    """确认幂等请求对相同参数稳定，并在实际参数变化时产生新身份。

    Returns:
        None；重复调用request ID相同而参数变化后不同则通过。
    """

    operations = _FakeOperationService()
    executor = CaseTemplateExecutorV4(operations)
    base_arguments = {"refundSerialNo": "RF-1"}

    executor._call_operation(
        "case-template-handoff-" + "a" * 20,
        SYSTEM_ID,
        "case-variant-v4-" + "b" * 20,
        "target",
        CANCEL_ID,
        base_arguments,
    )
    executor._call_operation(
        "case-template-handoff-" + "a" * 20,
        SYSTEM_ID,
        "case-variant-v4-" + "b" * 20,
        "target",
        CANCEL_ID,
        base_arguments,
    )
    executor._call_operation(
        "case-template-handoff-" + "a" * 20,
        SYSTEM_ID,
        "case-variant-v4-" + "b" * 20,
        "target",
        CANCEL_ID,
        {"refundSerialNo": "RF-2"},
    )

    request_ids = [request.request_id for _, request in operations.calls]
    assert request_ids[0] == request_ids[1]
    assert request_ids[0] != request_ids[2]


def test_generation_store_round_trips_dynamic_value_sources(tmp_path: Path) -> None:
    """确认持久化不会把动态引用的模型默认值误写成显式literal字段。

    Args:
        tmp_path: Pytest提供的系统知识目录临时根路径。

    Returns:
        None；Generation写入后可由严格模型完整重读时通过。
    """

    variants, issues = _compile_golden()
    generation = CaseTemplateGenerationV4(
        generation_id=f"case-template-generation-{'e' * 20}",
        system_id=SYSTEM_ID,
        operation_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{CANCEL_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_cancel_contract(),
        submission=_golden_submission(),
        issues=issues,
        variants=variants,
    )
    knowledge_store = Mock()
    knowledge_store.system_transaction.return_value = nullcontext()
    knowledge_store.system_root.return_value = tmp_path
    knowledge_store.workspace_revisions = Mock()
    generation_store = CaseTemplateGenerationStoreV4(knowledge_store)

    # 通过真实Store写入并回读，覆盖动态data_output、parameter和request_field的字段集语义。
    generation_store.write(generation)
    restored = generation_store.get(SYSTEM_ID, generation.generation_id)

    assert restored == generation


def test_query_list_uses_same_generic_compiler_and_executor_without_cancel_branch() -> None:
    """确认只读queryList的不同请求/响应结构走同一通用执行器。"""

    submission = CaseTemplateSubmission.model_validate(
        {
            "data_functions": [],
            "case_templates": [
                {
                    "template_id": "refund.query-list.pages",
                    "title": "分页查询",
                    "coverage_kind": "business",
                    "data_calls": [],
                    "parameters": [
                        {"name": "page", "target_field": "page", "function_id": "enum.values", "arguments": {"values": [1, 2]}}
                    ],
                    "constraints": [],
                    "request_bindings": [
                        {"field": "page", "source": {"kind": "parameter", "name": "page"}},
                        {"field": "pageSize", "source": {"kind": "literal", "value": 20}}
                    ],
                    "combination": "each",
                    "oracles": [
                        {
                            "oracle_id": "query_response",
                            "channel": "response",
                            "assertions": [
                                {"actual_path": "success", "operator": "eq", "expected": {"kind": "literal", "value": True}}
                            ]
                        }
                    ],
                    "evidence": [
                        {
                            "source_system_id": SYSTEM_ID,
                            "path": "RefundFacade.java",
                            "symbol": "RefundFacade#queryList",
                            "line": 1,
                        }
                    ]
                }
            ],
            "unresolved": []
        }
    )
    compilation = CaseTemplateCompilationInput(
        submission=submission,
        input_contract=_query_list_contract(),
        target_output_schema={"type": "object", "properties": {"success": {"type": "boolean"}, "list": {"type": "object"}}},
        runtime_registry=RuntimeFunctionRegistry(functions=[]),
        value_registry=CaseTemplateRegistryLoader().value_registry(),
        allowed_system_ids={SYSTEM_ID, BOOKING_SYSTEM_ID},
    )
    variants, issues = CaseTemplateCompilerV4().compile(compilation)
    generation = CaseTemplateGenerationV4(
        generation_id=f"case-template-generation-{'c' * 20}",
        system_id=SYSTEM_ID,
        operation_id=QUERY_LIST_ID,
        source_scan_id=SCAN_ID,
        coverage_id=f"coverage:{QUERY_LIST_ID}",
        runtime_registry_version="runtime-functions/v1",
        value_registry_version="value-functions/v1",
        status="READY",
        input_contract=_query_list_contract(),
        submission=submission,
        variants=variants,
    )

    results = CaseTemplateExecutorV4(_FakeOperationService()).execute(
        f"case-template-handoff-{'d' * 20}",
        generation,
        RuntimeFunctionRegistry(functions=[]),
    )

    assert issues == []
    assert len(variants) == 2
    assert [item.actual_request for item in results] == [{"page": 1, "pageSize": 20}, {"page": 2, "pageSize": 20}]
    assert {item.status for item in results} == {"COMPLETED"}
    assert all(len(item.operations) == 1 for item in results)


def test_v4_service_builds_finite_output_schema_from_scan_fields() -> None:
    """确认闭合泛型失败时仍可用同一扫描字段证据校验响应Oracle路径。

    Returns:
        None；queryList的分页与集合路径被有限Schema保留时通过。
    """

    capability = OperationCapability(
        operation_id=QUERY_LIST_ID,
        system_id=SYSTEM_ID,
        business_name="查询退票单列表",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        source_scan_id=SCAN_ID,
        publication_output_schema={},
        output_fields=[
            OperationFieldEvidence(field_path="list", field_name="list", declared_type="PageVO<SaasRefundOrderVO>"),
            OperationFieldEvidence(field_path="list.totalCount", field_name="totalCount", declared_type="int"),
            OperationFieldEvidence(field_path="list.pageList", field_name="pageList", declared_type="List<T>"),
            OperationFieldEvidence(
                field_path="saasOrderStateCounts",
                field_name="saasOrderStateCounts",
                declared_type="java.util.List<com.example.SaasOrderStateCountVO>",
            ),
        ],
    )
    service = CaseTemplateV4Service(Mock(), Mock(), Mock(), Mock())

    schema = service._target_output_schema(capability)

    assert schema["properties"]["list"]["properties"]["totalCount"] == {"type": "integer"}
    assert schema["properties"]["list"]["properties"]["pageList"] == {"type": "array", "items": {}}
    assert schema["properties"]["saasOrderStateCounts"] == {"type": "array", "items": {}}


def test_operation_output_fields_include_inherited_response_evidence() -> None:
    """确认Facade响应父类字段会进入Operation输出证据而无需V4硬编码公共字段。

    Returns:
        None；父类success与子类list字段都被扫描投影时通过。
    """

    source_ref = SourceReference(path="BaseResponse.java", symbol="BaseResponse", line=1)
    base_response = SemanticTypeDefinition(
        symbol_id="example.BaseResponse",
        qualified_class_name="example.BaseResponse",
        simple_name="BaseResponse",
        fields=[
            SemanticFieldDefinition(
                field_name="success",
                declared_type="boolean",
                source_ref=source_ref,
            )
        ],
        source_ref=source_ref,
    )
    list_response = SemanticTypeDefinition(
        symbol_id="example.ListResponse",
        qualified_class_name="example.ListResponse",
        simple_name="ListResponse",
        base_types=["example.BaseResponse"],
        fields=[
            SemanticFieldDefinition(
                field_name="list",
                declared_type="PageVO<OrderVO>",
                source_ref=SourceReference(path="ListResponse.java", symbol="ListResponse#list", line=2),
            )
        ],
        source_ref=SourceReference(path="ListResponse.java", symbol="ListResponse", line=1),
    )
    analysis = SemanticAnalysisResult(
        system_id=SYSTEM_ID,
        types=[base_response, list_response],
    )
    catalog = OperationCapabilityCatalog.__new__(OperationCapabilityCatalog)

    # 直接验证字段投影纯逻辑，避免把V4行为错误地绑定到某个具体Facade或响应基类名称。
    fields = catalog._type_field_evidence(list_response, analysis)

    assert [(field.field_path, field.declared_type) for field in fields] == [
        ("success", "boolean"),
        ("list", "PageVO<OrderVO>"),
    ]


def test_start_request_accepts_raw_and_canonical_operation_paths() -> None:
    """确认API请求模型和入口解析同时支持原始路径与facade canonical ID。"""

    entry = Mock(kind=KnowledgeNodeKind.FACADE, entry_id=CANCEL_ID)
    service = CaseTemplateV4Service(Mock(), Mock(), Mock(), Mock())

    raw = CaseTemplateGenerationStartRequest(operation_id=CANCEL_ID.removeprefix("facade:"))
    canonical = CaseTemplateGenerationStartRequest(operation_id=CANCEL_ID)

    assert service._resolve_entry([entry], raw.operation_id) is entry
    assert service._resolve_entry([entry], canonical.operation_id) is entry


def test_v4_service_rebuilds_stale_input_contract_from_current_scan_operation() -> None:
    """确认源码重扫后无需重发自然语言知识即可重建请求契约。

    Returns:
        None；返回契约绑定新scan且保留源码声明必填字段时通过。
    """

    stale_contract = _cancel_contract().model_copy(
        update={"source_scan_id": "scan-refund-v4-stale"}
    )
    node = KnowledgeNode(
        node_id="entry-refund-cancel",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title="取消退票单",
        aliases=[CANCEL_ID],
        input_contract=stale_contract,
    )
    operation = OperationCapability(
        operation_id=CANCEL_ID,
        system_id=SYSTEM_ID,
        business_name="取消退票单",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.WRITE,
        input_schema={
            "type": "object",
            "properties": {"refundSerialNo": {"type": "string"}},
            "additionalProperties": False,
        },
        publication_input_schema={
            "type": "object",
            "properties": {"refundSerialNo": {"type": "string"}},
            "additionalProperties": False,
        },
        input_fields=[
            OperationFieldEvidence(
                field_path="refundSerialNo",
                field_name="refundSerialNo",
                declared_type="String",
                annotations=["@required"],
                documentation_required=True,
            )
        ],
        provider_kind=OperationProviderKind.DSF_PROXY,
        provider_operation_id="dsf:refund:cancel",
        source_scan_id=SCAN_ID,
        executable=True,
    )
    store = Mock()
    store.list_nodes.return_value = [(node, Path("node.md"), "")]
    catalog = Mock()
    catalog.derive.return_value = [operation]
    service = CaseTemplateV4Service(
        store,
        Mock(),
        Mock(),
        Mock(),
        CaseTemplateV4RuntimeServices(
            operation_catalog=catalog,
            operation_service=Mock(),
            codex_app_server=Mock(),
            environment_provider=default_case_template_environment_values,
        ),
    )

    contract = service._input_contract(SYSTEM_ID, CANCEL_ID, SCAN_ID)

    assert contract.source_scan_id == SCAN_ID
    assert contract.status == "READY"
    assert contract.request_schema["required"] == ["refundSerialNo"]


def test_input_contract_merges_duplicate_inherited_field_paths() -> None:
    """确认父子类型重复字段证据只生成一个绑定并保留具体请求类型。

    Returns:
        None；重复page字段被合并且子类必填证据生效时通过。
    """

    base_ref = SourceReference(
        path="BasePageRequest.java",
        symbol="example.BasePageRequest#page",
        line=10,
    )
    concrete_ref = SourceReference(
        path="RefundOrderQueryRequest.java",
        symbol="example.RefundOrderQueryRequest#page",
        line=20,
    )
    operation = OperationCapability(
        operation_id=QUERY_LIST_ID,
        system_id=SYSTEM_ID,
        business_name="查询退票单",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema={
            "type": "object",
            "properties": {"page": {"type": "integer"}},
            "additionalProperties": False,
        },
        input_fields=[
            OperationFieldEvidence(
                field_path="page",
                field_name="page",
                declared_type="Integer",
                source_ref=base_ref,
            ),
            OperationFieldEvidence(
                field_path="page",
                field_name="page",
                declared_type="Integer",
                documentation_required=True,
                source_ref=concrete_ref,
            ),
        ],
        source_scan_id=SCAN_ID,
    )
    node = KnowledgeNode(
        node_id="entry-refund-query-list",
        system_id=SYSTEM_ID,
        kind=KnowledgeNodeKind.FACADE,
        title="查询退票单",
        aliases=[QUERY_LIST_ID],
    )

    contract = OperationInputKnowledgeBuilder().build(operation, node, SCAN_ID)

    assert contract.request_type == "example.RefundOrderQueryRequest"
    assert [field.path for field in contract.fields] == ["page"]
    assert contract.fields[0].required is True


def test_v4_service_resolves_request_model_before_saved_and_catalog_defaults() -> None:
    """确认V4模型字段按单次请求、本机设置和Codex目录默认逐级解析。

    Returns:
        None；单次模型覆盖与本机effort组合在创建handoff前交给目录校验时通过。
    """

    catalog = CodexModelCatalog(
        provider_id="company",
        default_model="company-default",
        models=(
            CodexModelOption(
                model_id="company-request",
                display_name="Company Request",
                default_reasoning_effort="medium",
                supported_reasoning_efforts=("medium", "high"),
            ),
        ),
    )
    codex = Mock()
    codex.validate_model_profile.return_value = (
        catalog,
        catalog.models[0],
        "high",
    )
    service = CaseTemplateV4Service(
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=Mock(),
            codex_app_server=codex,
            environment_provider=default_case_template_environment_values,
            runtime_settings_provider=lambda: RuntimeToolSettings(
                case_template_v4_model="company-saved",
                case_template_v4_reasoning_effort="high",
            ),
        ),
    )

    profile = service._resolve_model_profile(
        CaseTemplateGenerationStartRequest(
            operation_id=CANCEL_ID,
            codex_model="company-request",
        )
    )

    codex.validate_model_profile.assert_called_once_with("company-request", "high")
    assert profile.provider_id == "company"
    assert profile.model == "company-request"
    assert profile.reasoning_effort == "high"


def test_v4_service_creates_thread_and_starts_turn_with_v4_tool_scope() -> None:
    """确认V4 handoff绑定Codex深链并立即启动同线程turn。"""

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'f' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
        model_provider="custom",
        codex_model="company-case-model",
        reasoning_effort="high",
    )
    codex = Mock()
    codex.create_scoped_turn.return_value = CodexStartedTurn(
        thread_id="thread-v4-service",
        deep_link="codex://threads/thread-v4-service",
        turn_id="turn-v4-service",
        process_id="12345",
        model_provider="custom",
        model="company-case-model",
        reasoning_effort="high",
        turn_status="inProgress",
    )
    handoffs = Mock()
    service = CaseTemplateV4Service(
        Mock(),
        Mock(),
        Mock(),
        handoffs,
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=Mock(),
            codex_app_server=codex,
            environment_provider=default_case_template_environment_values,
        ),
    )

    started = service._start_codex_turn(handoff)

    request = codex.create_scoped_turn.call_args.args[0]
    assert request.tool_scope == "case_template_v4"
    assert request.model_provider == "custom"
    assert request.model == "company-case-model"
    assert request.reasoning_effort == "high"
    assert started.thread_id == "thread-v4-service"
    assert started.codex_deep_link == "codex://threads/thread-v4-service"
    assert started.turn_process_id == "12345"
    assert started.turn_id == "turn-v4-service"
    assert started.turn_status == "inProgress"


def test_v4_dsl_submission_dispatches_qa_without_waiting_for_execution() -> None:
    """确认DSL严格落盘后通过后台任务执行QA而不阻塞MCP请求。

    Returns:
        None；handoff进入EXECUTING、任务已派发且当前线程未调用执行器时通过。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'9' * 20}",
        system_id=SYSTEM_ID,
        entry_id=QUERY_LIST_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
        execution_mode="QA_AFTER_GENERATION",
    )
    submission = CaseTemplateSubmission.model_validate(
        {
            "data_functions": [],
            "case_templates": [
                {
                    "template_id": "refund.query-list.background",
                    "title": "分页查询后台执行",
                    "coverage_kind": "business",
                    "data_calls": [],
                    "parameters": [],
                    "constraints": [],
                    "request_bindings": [
                        {"field": "page", "source": {"kind": "literal", "value": 1}},
                        {"field": "pageSize", "source": {"kind": "literal", "value": 20}},
                    ],
                    "combination": "each",
                    "oracles": [
                        {
                            "oracle_id": "query-success",
                            "channel": "response",
                            "assertions": [
                                {
                                    "actual_path": "success",
                                    "operator": "eq",
                                    "expected": {"kind": "literal", "value": True},
                                }
                            ],
                        }
                    ],
                    "evidence": [
                        {
                            "source_system_id": SYSTEM_ID,
                            "path": "RefundFacade.java",
                            "symbol": "RefundFacade#queryList",
                            "line": 1,
                        }
                    ],
                }
            ],
            "unresolved": [],
        }
    )
    capability = OperationCapability(
        operation_id=QUERY_LIST_ID,
        system_id=SYSTEM_ID,
        business_name="查询退票单",
        kind=OperationKind.FACADE,
        mutability=OperationMutability.READ_ONLY,
        input_schema=_query_list_contract().request_schema,
        publication_output_schema={
            "type": "object",
            "properties": {
                "output": {
                    "type": "object",
                    "properties": {"success": {"type": "boolean"}},
                }
            },
        },
        source_scan_id=SCAN_ID,
        executable=True,
    )
    handoffs = Mock()
    handoffs.get.return_value = handoff
    handoffs.accessed_paths.return_value = {SYSTEM_ID: {"RefundFacade.java"}}
    handoffs.accessed_outer_provider_ids.return_value = set()
    handoffs.accessed_ranges.return_value = {
        SYSTEM_ID: {"RefundFacade.java": [(1, 10)]}
    }
    generations = Mock()
    generations.write.side_effect = lambda generation: generation
    task_manager = Mock()
    runtime = CaseTemplateV4RuntimeServices(
        operation_catalog=Mock(),
        operation_service=Mock(),
        codex_app_server=Mock(),
        environment_provider=default_case_template_environment_values,
        task_manager=task_manager,
    )
    service = CaseTemplateV4Service(Mock(), Mock(), generations, handoffs, runtime)
    service._require_current_source_scopes = Mock()
    service._input_contract = Mock(return_value=_query_list_contract())
    service._runtime_capabilities = Mock(return_value=[capability])
    service._evidence_source_texts = Mock(
        return_value={SYSTEM_ID: {"RefundFacade.java": "RefundFacade queryList"}}
    )
    service.executor = Mock()

    generation = service._submit_exclusive(handoff.handoff_id, submission)

    written_statuses = [call.args[0].status for call in handoffs.write.call_args_list]
    assert generation.status == "READY"
    assert written_statuses[-1] == "EXECUTING"
    task_manager.submit.assert_called_once()
    service.executor.execute.assert_not_called()


def test_v4_service_marks_atomic_thread_turn_start_failure() -> None:
    """确认同会话线程/turn启动失败时立即返回FAILED。

    Returns:
        None；未取得App Server turn回执时不得伪造thread或WAITING状态。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'c' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
        model_provider="company",
        codex_model="company-case",
        reasoning_effort="high",
    )
    codex = Mock()
    codex.create_scoped_turn.side_effect = ExecutionFailure("turn failed")
    handoffs = Mock()
    service = CaseTemplateV4Service(
        Mock(),
        Mock(),
        Mock(),
        handoffs,
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=Mock(),
            codex_app_server=codex,
            environment_provider=default_case_template_environment_values,
        ),
    )

    failed = service._start_codex_turn(handoff)

    assert failed.status == "FAILED"
    assert failed.thread_id == ""
    assert failed.codex_deep_link == ""


def test_v4_service_marks_exited_turn_without_submission_failed() -> None:
    """确认Codex退出且没有DSL时轮询不会永久停在WAITING。

    Returns:
        None；handoff被安全持久化为FAILED时通过。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'a' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
        thread_id="thread-v4-failed-turn",
        turn_process_id="12345",
        turn_id="turn-v4-failed",
        turn_status="inProgress",
    )
    codex = Mock()
    codex.inspect_case_turn_process.return_value = CodexCaseTurnProcessSnapshot(
        state="EXITED",
        return_code=1,
    )
    codex.inspect_thread.return_value = CodexThreadSnapshot(
        thread_id="thread-v4-failed-turn",
        deep_link="codex://threads/thread-v4-failed-turn",
        turn_count=1,
        latest_turn_id="turn-v4-failed",
        latest_turn_status="failed",
        latest_turn_error="Codex turn failed (code=unauthorized, http_status=401)",
    )
    handoffs = Mock()
    handoffs.get.return_value = handoff
    handoffs.processing_scope.return_value = nullcontext()
    service = CaseTemplateV4Service(
        Mock(),
        Mock(),
        Mock(),
        handoffs,
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=Mock(),
            codex_app_server=codex,
            environment_provider=default_case_template_environment_values,
        ),
    )

    refreshed = service._refresh_agent_status(handoff)

    assert refreshed.status == "FAILED"
    assert refreshed.turn_status == "failed"
    assert refreshed.safe_error == "Codex turn failed (code=unauthorized, http_status=401)"
    handoffs.write.assert_called_once_with(refreshed)


def test_v4_service_does_not_read_thread_from_second_server_while_turn_runs() -> None:
    """活跃V4 turn轮询不得用第二个App Server读取并误写interrupted状态。

    Returns:
        None；owner进程运行时保持WAITING/inProgress且不调用thread/read。

    Side Effects:
        仅调用内存状态桩，不启动真实App Server、MCP或模型turn。
    """

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'b' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
        thread_id="thread-v4-running-turn",
        turn_process_id="67890",
        turn_id="turn-v4-running",
        turn_status="inProgress",
    )
    codex = Mock()
    codex.inspect_case_turn_process.return_value = CodexCaseTurnProcessSnapshot(state="RUNNING")
    handoffs = Mock()
    handoffs.get.return_value = handoff
    handoffs.processing_scope.return_value = nullcontext()
    service = CaseTemplateV4Service(
        Mock(),
        Mock(),
        Mock(),
        handoffs,
        CaseTemplateV4RuntimeServices(
            operation_catalog=Mock(),
            operation_service=Mock(),
            codex_app_server=codex,
            environment_provider=default_case_template_environment_values,
        ),
    )

    # 活跃owner进程是运行状态真相源；持久线程仅在它退出后读取终态。
    refreshed = service._refresh_agent_status(handoff)

    assert refreshed.status == "WAITING_FOR_AGENT"
    assert refreshed.turn_status == "inProgress"
    codex.inspect_thread.assert_not_called()
    handoffs.write.assert_not_called()


def test_handoff_catalog_never_exposes_registered_source_root() -> None:
    """确认轮询目录即使包含线程和执行结果也不会泄漏源码绝对路径。"""

    handoff = CaseTemplateHandoffV4(
        handoff_id=f"case-template-handoff-{'e' * 20}",
        system_id=SYSTEM_ID,
        entry_id=CANCEL_ID,
        source_scan_id=SCAN_ID,
        status="WAITING_FOR_AGENT",
        source_scopes=[
            CaseTemplateSourceScope(
                source_system_id=SYSTEM_ID,
                source_scan_id=SCAN_ID,
                source_baseline=SourceBaseline(source_path="/private/refund-core"),
            )
        ],
    )
    handoffs = Mock()
    handoffs.get.return_value = handoff
    service = CaseTemplateV4Service(Mock(), Mock(), Mock(), handoffs)
    service._input_contract = Mock(return_value=_cancel_contract())

    catalog = service.catalog(handoff.handoff_id)

    assert "/private/refund-core" not in json.dumps(catalog, ensure_ascii=False)
    assert catalog["handoff"]["source_scopes"] == [
        {"source_system_id": SYSTEM_ID, "source_scan_id": SCAN_ID}
    ]
