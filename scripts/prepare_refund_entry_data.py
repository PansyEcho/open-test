"""入口实验的固定版本造数函数：复用真实出票数据，通过业务接口新建并回查退票单。"""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from scripts import benchmark_refund_models as models
from scripts import benchmark_refund_qa as qa

GENDERS = {"NONE": 0, "M": 1, "F": 2, "MI": 3, "FI": 4}
CREDIT_TYPES = {"NONE": 0, "PP": 1, "GA": 2, "TW": 3, "TB": 4, "HX": 5, "HY": 6, "QT": 9}


def exact_integer(value: Any) -> int:
    """将DSF返回的整数型浮点数转为Facade整数契约；拒绝小数和布尔值以免改写真实含义。"""
    # Python的int会截断小数并接受bool；业务枚举必须保留原始数值，不能静默纠正。
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError("non_integer_source_value")
    return int(value)


def create_request_v1(order: dict[str, Any], psi: dict[str, Any]) -> dict[str, Any]:
    """从已验证成年乘客的真实出票关系构建自愿退票请求；未知枚举抛错，不替换业务身份。"""
    passenger = psi["passenger"]
    segment = psi["segment"]
    # 字段映射来自已验证创建Case；枚举按登记源码GenderEnum/CreditTypeEnum转换真实值。
    passenger_payload = {field: passenger[field] for field in
                         ("lastName", "firstName", "creditNo", "birthday", "nationCode")}
    passenger_payload.update(passengerType=0, gender=GENDERS[passenger["gender"]], creditType=CREDIT_TYPES[passenger["creditType"]],
                             gmtCreditValidate=datetime.strptime(passenger["gmtCreditValidate"], "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d %H:%M:%S"))
    segment_payload = {field: segment[field] for field in (
        "sequence", "flightNo", "carrierName", "departureCityCode", "departureCity", "arrivalCityCode", "arrivalCity",
        "departureAirportCode", "departureAirport", "arrivalAirportCode", "arrivalAirport") if segment.get(field) is not None}
    # DSF数值可能是8.0/1.0；Facade严格要求integer，可选的空carrierName则不发送。
    segment_payload["sequence"] = exact_integer(segment["sequence"])
    segment_payload.update(carrierCode=segment["carrier"], actualCarrierCode=segment["realCarrier"])
    for source, target in (("gmtTakeOff", "gmtTakeOff"), ("gmtArrive", "gmtArrival")):
        segment_payload[target] = datetime.strptime(segment[source], "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d %H:%M:%S")
    return {"operator": "OpenTest", "isAuto": False, "orderChannelSource": exact_integer(order["orderChannelSource"]),
            "memberId": order["memberId"], "passengerIds": [passenger["passengerId"]], "segmentIds": [segment["segmentId"]],
            "refundDetailApiDTO": {"orderRefundInfo": {"orderSerialNo": order["orderSerialNo"], "refundSubCategory": 1},
                                    "segmentRefundInfos": [segment_payload],
                                    "refundItemInfos": [{"passenger": passenger_payload, "passSegs": [{"segmentInfo": segment_payload}]}]}}


def verified_booking_v1(order: dict[str, Any], refunds: list[dict[str, Any]], changes: dict[str, Any]) -> dict[str, Any]:
    """核对真实出票详情及无进行中订单条件，返回一个可重新申请退票的单票乘客航段关系。"""
    # 原共享方法只接受无退票历史，本版本允许全部历史已取消；不能放行其他失败或活动状态。
    if not isinstance(refunds, list) or any(refund.get("refundState") != "REFUND_CANCEL" for refund in refunds):
        raise ValueError("booking_has_active_or_finished_refund")
    if changes.get("totalCount") != 0 or changes.get("pageList") != []:
        raise ValueError("booking_has_change_order")
    if order.get("orderState") != "TICKETED" or order.get("gds") == "SAPL":
        raise ValueError("booking_not_supported")
    for psi in order.get("psis", []):
        passenger = psi.get("passenger") or {}
        ticket = (psi.get("item") or {}).get("ticketNo")
        if (passenger.get("passengerType") != "ADT" or passenger.get("gender") not in GENDERS
                or passenger.get("creditType") not in CREDIT_TYPES or not ticket):
            continue
        _, mapping = models.make_state("票号" + ticket)
        if list(mapping.values()) == [ticket]:
            return psi
    raise ValueError("booking_has_no_supported_ticket")


def prepare_operation(operation: str, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
    """调用已登记的四个只读数据接口，返回真实业务输出；拒绝扩展到任意操作。"""
    # 造数只沿已登记的出票、退票及改签查询链取数，不接受模型传入任意操作。
    allowed = {"dsf:iflightchainsaas.booking.core:trade:queryList", "dsf:iflightchainsaas.booking.core:trade:queryDetail",
               "dsf:ifightchainsaas.endorse.core:change:queryList", qa.FACADE + "queryListByOrderNo"}
    if operation not in allowed:
        raise ValueError("unregistered_preparation_action")
    record = qa.api_call("POST", f"/systems/{qa.SYSTEM}/operation-executions",
                         {"environment": "qa", "operation_id": operation, "arguments": {"traceId": request_id, **arguments},
                          "request_id": request_id, "timeout_seconds": 60})["execution"]
    business = record.get("result") or {}
    output = business.get("output") or {}
    if record.get("status") != "completed" or business.get("status") != "success" or output.get("success") is not True:
        raise ValueError("preparation_query_failed")
    return output


def find_booking_v1(request_prefix: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """沿共享函数已登记的查询链动态寻找可用原订单，不固定票号，也不选择有活动改签的首条数据。"""
    listing = prepare_operation("dsf:iflightchainsaas.booking.core:trade:queryList", {"page": 1, "pageSize": 1000}, request_prefix + "-bookings")
    page = listing.get("list") or {}
    if page.get("totalCount") != len(page.get("pageList", [])):
        raise ValueError("incomplete_booking_candidates")
    for index, candidate in enumerate(page["pageList"]):
        if candidate.get("orderState") != "TICKETED" or candidate.get("gds") == "SAPL":
            continue
        order_no = candidate["orderSerialNo"]
        detail = prepare_operation("dsf:iflightchainsaas.booking.core:trade:queryDetail", {"orderSerialNo": order_no}, f"{request_prefix}-detail-{index}")
        order = detail.get("saasOrderVO") or {}
        if order.get("orderSerialNo") != order_no:
            raise ValueError("booking_identity_not_verified")
        refunds = prepare_operation(qa.FACADE + "queryListByOrderNo", {"orderSerialNo": order_no}, f"{request_prefix}-refunds-{index}")
        changes = prepare_operation("dsf:ifightchainsaas.endorse.core:change:queryList", {"orderSerialNo": order_no, "page": 1, "pageSize": 1000}, f"{request_prefix}-changes-{index}")
        try:
            psi = verified_booking_v1(order, refunds.get("list"), changes.get("list") or {})
            return order, psi
        except ValueError:
            # 数据不满足已验证业务条件时继续找其他原订单，不修改已有业务状态来制造可用性。
            continue
    raise ValueError("no_available_booking_for_new_refund")


def prepare_refund_entry_v1(request_prefix: str) -> dict[str, Any]:
    """为一个槽位动态新建不同退票单并回查；稳定请求键恢复未知写入，耗时全部归入准备阶段。"""
    started = time.perf_counter()
    order, psi = find_booking_v1(request_prefix)
    ticket = psi["item"]["ticketNo"]
    arguments = create_request_v1(order, psi)
    arguments["traceId"] = request_prefix
    create_id = request_prefix + "-create"
    record = qa.known_execution(create_id)
    if record is None:
        try:
            record = qa.api_call("POST", f"/systems/{qa.SYSTEM}/operation-executions",
                                 {"environment": "qa", "operation_id": qa.FACADE + "createOrder", "arguments": arguments,
                                  "request_id": create_id, "timeout_seconds": 60})["execution"]
        except Exception:
            # 响应丢失也不重复写入，仍从记录及随后真实查询诊断；未知结果不成为准备成功。
            record = qa.known_execution(create_id) or {}
    # 读请求也会去重；恢复观察必须用新键，避免第一次未落地的旧快照永久遮住后续真实结果。
    observation_id = request_prefix + "-observe-" + str(time.time_ns())
    listing, listed = qa.execute("queryList", {"ticketNo": ticket, "page": 1, "pageSize": 1000}, observation_id + "-list")
    candidates = [refund for refund in (listing.get("list") or {}).get("pageList", []) if refund.get("refundState") in qa.CANCELLABLE]
    if len(candidates) != 1:
        raise ValueError("created_refund_not_unique")
    target = qa.eligible_refund(listing, candidates[0]["refundSerialNo"])
    detail, observed = qa.execute("queryDetailByRefundNo", {"refundSerialNo": target["refundSerialNo"]}, observation_id + "-detail")
    actual = detail.get("saasRefundOrderVO") or {}
    actual_tickets = {relation.get("item", {}).get("ticketNo") for relation in actual.get("psis", [])}
    if (actual.get("refundSerialNo") != target["refundSerialNo"] or actual.get("orderSerialNo") != order["orderSerialNo"]
            or actual.get("refundState") != "PENDING_APPLY" or ticket not in actual_tickets):
        raise ValueError("created_refund_identity_or_state_mismatch")
    business = record.get("result") or {}
    if record.get("status") != "completed" or business.get("status") != "success" or not (business.get("output") or {}).get("success"):
        raise ValueError("create_outcome_requires_inspection")
    return {"function": "prepare_refund_entry_v1", "version": 1, "refund_no": target["refundSerialNo"],
            "ticket": ticket, "state": actual["refundState"], "create_execution": record["execution_id"],
            "readback": [listed, observed], "preparation_ms": (time.perf_counter() - started) * 1000}
