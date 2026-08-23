"""在Booking.Core与Refund.Core人工真值样本上验证Java语义分析门禁。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from opentest.adapters.semantic_analysis import JavaParserSemanticAnalyzer
from opentest.application.semantic_spike import PatternExpectation, verify_patterns
from opentest.domain.models import SemanticAnalysisResult


@dataclass(frozen=True)
class EdgeExpectation:
    """描述一条人工核对过的代表性源码调用边。"""

    caller_fragment: str
    action: str
    callee_fragment: str


BOOKING_EDGES = (
    EdgeExpectation("OrderFacadeImpl#orderDetail", "execute", "AbstractFacade#execute"),
    EdgeExpectation("CreateOrderProcessor#", "createOrder", "MerchantApiService#createOrder"),
    EdgeExpectation("CreateOrderProcessor#", "getOrderVO", "AbstractOrderTaskProcessor#getOrderVO"),
    EdgeExpectation("MerchantApiServiceImpl#createOrder", "build", "OrderCreateApiRequestBuilder#build"),
    EdgeExpectation("MerchantApiServiceImpl#createOrder", "isOccupying", "MerchantApiServiceImpl#isOccupying"),
    EdgeExpectation("MerchantApiServiceImpl#createOrder", "setState", "StateDelegate#setState"),
    EdgeExpectation("CreateOrderRequestCheckChain#check", "check", "CreateOrderRequestChecker#check"),
    EdgeExpectation("TradeFacadeImpl#createOrder", "currentTimeMillis", "System#currentTimeMillis"),
    EdgeExpectation("TradeFacadeImpl#createOrder", "getBookInfo", "CreateOrderRequest#getBookInfo"),
    EdgeExpectation("TradeFacadeImpl#createOrder", "setTraceId", "BaseRequest#setTraceId"),
)

REFUND_EDGES = (
    EdgeExpectation("RefundFacadeImpl#queryListByOrderNo", "createErrorResponse", "AbstractFacade#createErrorResponse"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "accountCheckSenderTask", "RefundOrderSuccessPostActor#accountCheckSenderTask"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "addEmailTask", "AbstractOrderPostTransitActor#addEmailTask"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "addPayNotifyTask", "AbstractOrderPostTransitActor#addPayNotifyTask"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "addSupplementOrSyncSuccessTasks", "RefundOrderSuccessPostActor#addSupplementOrSyncSuccessTasks"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "addTicketedJourneySenderTask", "RefundOrderSuccessPostActor#addTicketedJourneySenderTask"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "addWalletRefundTask", "RefundOrderSuccessPostActor#addWalletRefundTask"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "getData", "StateContext#getData"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "getProperties", "StateContext#getProperties"),
    EdgeExpectation("RefundOrderSuccessPostActor#addTask", "isSupplementOrSyncSuccess", "RefundOrderSuccessPostActor#isSupplementOrSyncSuccess"),
    EdgeExpectation("RefundOrderFailPostActor#addTask", "addTicketNotifyTask", "AbstractOrderPostTransitActor#addTicketNotifyTask"),
    EdgeExpectation("RefundOrderDonePostActor#addTask", "addLogTask", "AbstractOrderPostTransitActor#addLogTask"),
)

REFUND_STATE_LABELS = {
    "DEFAULT_REFUND": "无效",
    "PENDING_APPLY": "退票申请",
    "RESHOPING": "核价中",
    "AUDITED": "审核通过",
    "WAIT_REFUND": "待退票",
    "REFUNDING": "退票中",
    "REFUND_SUCCESS": "退票成功",
    "REFUND_FAIL": "退票失败",
    "REFUND_CANCEL": "已取消",
    "REFUND_DONE": "退款完成",
}

BOOKING_PATTERNS = (
    PatternExpectation("responsibility_chain", "CreateOrderRequestCheckChain#check"),
    PatternExpectation("state_machine", ".biz.actor.pre."),
    PatternExpectation("state_machine", ".biz.actor.post."),
    PatternExpectation("state_machine", ".biz.fsm.OrderStateMachineStarter#"),
)

REFUND_PATTERNS = (
    PatternExpectation("state_machine", ".biz.actor.pre."),
    PatternExpectation("state_machine", ".biz.actor.post."),
    PatternExpectation("state_machine", ".biz.fsm.core.OrderStateMachineStarter#"),
)


def verify_edges(
    analysis: SemanticAnalysisResult,
    expectations: tuple[EdgeExpectation, ...],
) -> tuple[int, list[str]]:
    """对比人工真值与解析器的调用方、动作和目标符号。

    Args:
        analysis: 目标真实仓库的完整语义分析结果。
        expectations: 人工核对源码后固定的代表性调用边。

    Returns:
        匹配数量和不含源码正文的失败样本标识。
    """

    matched = 0
    failures: list[str] = []
    for expected in expectations:
        candidates = [
            edge
            for edge in analysis.call_edges
            if expected.caller_fragment in edge.caller_symbol_id and edge.callee_expression == expected.action
        ]
        if any(
            edge.resolution_status.value == "resolved" and expected.callee_fragment in edge.callee_symbol_id
            for edge in candidates
        ):
            matched += 1
        else:
            failures.append(f"{expected.caller_fragment}->{expected.action}")
    return matched, failures


def verify_refund_state_labels(analysis: SemanticAnalysisResult) -> list[str]:
    """验证RefundOrderStateEnum全部常量的中文name字段绑定。

    Args:
        analysis: Refund.Core语义分析结果。

    Returns:
        缺失或展示名不符的枚举code列表。
    """

    actual = {
        value.code: value.display_name
        for value in analysis.enum_values
        if value.enum_type.endswith("RefundOrderStateEnum") and value.description_field == "name"
    }
    return [code for code, display_name in REFUND_STATE_LABELS.items() if actual.get(code) != display_name]


def parse_args() -> argparse.Namespace:
    """解析两个真实仓库和本地Sidecar JAR路径。

    Returns:
        三个必填路径组成的命令行命名空间。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--booking-root", type=Path, required=True)
    parser.add_argument("--refund-root", type=Path, required=True)
    parser.add_argument("--analyzer-jar", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """运行两个真实仓库Spike并以机器可读摘要返回门禁结果。

    Returns:
        调用边召回率至少90%、状态标签全对、模式无误报且人工真值齐全时返回0，否则返回1。
    """

    arguments = parse_args()
    analyzer = JavaParserSemanticAnalyzer(arguments.analyzer_jar)
    # 两个项目分别分析，避免共享类型求解器造成跨系统调用边污染。
    booking = analyzer.analyze(
        "travelsystem.java.dsf.supplychain.booking.core",
        arguments.booking_root,
    )
    refund = analyzer.analyze(
        "ifightchainsaas.java.refund.core",
        arguments.refund_root,
    )
    booking_matches, booking_failures = verify_edges(booking, BOOKING_EDGES)
    refund_matches, refund_failures = verify_edges(refund, REFUND_EDGES)
    total_samples = len(BOOKING_EDGES) + len(REFUND_EDGES)
    matched_samples = booking_matches + refund_matches
    edge_recall = matched_samples / total_samples
    state_failures = verify_refund_state_labels(refund)
    booking_true_positives, booking_unexpected, booking_missing = verify_patterns(booking, BOOKING_PATTERNS)
    refund_true_positives, refund_unexpected, refund_missing = verify_patterns(refund, REFUND_PATTERNS)
    unexpected_patterns = [*booking_unexpected, *refund_unexpected]
    missing_patterns = [*booking_missing, *refund_missing]
    true_positive_patterns = booking_true_positives + refund_true_positives
    high_confidence_patterns = true_positive_patterns + len(unexpected_patterns)
    pattern_precision = true_positive_patterns / high_confidence_patterns if high_confidence_patterns else 0.0
    passed = (
        edge_recall >= 0.9
        and not state_failures
        and not unexpected_patterns
        and not missing_patterns
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "edge_recall": round(edge_recall, 4),
                "matched_edges": matched_samples,
                "total_edges": total_samples,
                "booking_edge_failures": booking_failures,
                "refund_edge_failures": refund_failures,
                "refund_state_label_failures": state_failures,
                "pattern_precision": round(pattern_precision, 4),
                "high_confidence_pattern_true_positives": true_positive_patterns,
                "unexpected_high_confidence_patterns": unexpected_patterns,
                "missing_expected_patterns": missing_patterns,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
