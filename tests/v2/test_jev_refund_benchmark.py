"""验证模型对照的身份边界、失败计分和真实取消回查约束。"""

import json
from pathlib import Path

import pytest

from scripts import benchmark_refund_models as models
from scripts import benchmark_refund_qa as qa


def test_candidates_preserve_duplicates_and_second_target():
    """重复票号必须归为同一候选，第二目标仍可逆映射且外发上下文不含真实票号。"""
    # 重复出现第二张票不能改变第二候选的编号和原文位置。
    text = "保留TTT4102161000018，只取消TTT4102161000019，重复确认TTT4102161000019"
    state, mapping = models.make_state(text)
    assert mapping == {"t1": "TTT4102161000018", "t2": "TTT4102161000019"}
    assert all(ticket not in json.dumps(state) for ticket in mapping.values())
    assert state["user_request"].count("TICKET_2") == 2


def test_overlapping_numeric_and_prefixed_tickets_are_masked_atomically():
    """短数字票号是长号/带前缀号的子串时仍各自完整替换，返回的候选关联不失真。"""
    # 逐个字符串替换会产生TICKET_11或TTTTICKET_1，原子正则替换必须消除这类污染。
    state, mapping = models.make_state("保留1234567890，只取消12345678901的退票单；另有TTT1234567890。")
    assert state["user_request"] == "保留TICKET_1，只取消TICKET_2的退票单；另有TICKET_3。"
    assert mapping == {"t1": "1234567890", "t2": "12345678901", "t3": "TTT1234567890"}


@pytest.mark.parametrize("decision", [
    {"intent": "cancel_refund", "action": "execute", "target": "invented", "reason": "automatic"},
    {"intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic", "api": "delete"},
    {"intent": "cancel_refund"},
])
def test_invalid_output_never_becomes_a_business_identifier(decision):
    """未知候选、多余字段和缺字段均拒绝，不把生成字符串变为业务参数。"""
    # 模型只能引用调用前已经提取的候选，不能自造目标。
    state, _ = models.make_state("取消TTT4102161000018的退票")
    with pytest.raises(ValueError):
        models.validate_decision(decision, models.questions_for(state))


def test_scoring_keeps_errors_and_wrong_targets():
    """快速失败仍计入准确率分母但不降低成功延迟；选错票号计为不安全路由。"""
    # 反例保留取消意图但选择另一张票，仍应计入误路由。
    sample = {"id": "negative", "expected": ["cancel_refund", "execute", "t2", "automatic"]}
    wrong = {"ok": True, "arm": "jev", "client_ms": 1000,
             "decision": {"intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic"}}
    failure = {"ok": False, "arm": "jev", "client_ms": 1}
    rows = [models.score_sample(sample, wrong), models.score_sample(sample, failure)]
    summary = models.summarize(rows)["jev"]
    assert summary["accuracy"] == 0
    assert summary["unsafe_routes"] == 1
    assert summary["median_client_ms"] == 1000
    assert summary["failed_elapsed_ms"] == [1]


def test_labels_never_enter_model_input():
    """开发和验收分区独立，标注不进入模型题面，所有样例在同一闭集下合法。"""
    fixture = json.loads((models.ROOT / "tests/fixtures/jev-refund-cases.json").read_text())
    assert len(fixture["development"]) == 10
    assert len(fixture["heldout"]) == 20
    assert not {case["text"] for case in fixture["development"]} & {case["text"] for case in fixture["heldout"]}
    # 不依赖模型输出生成金标，先校验人工定义的输入契约。
    for case in fixture["development"] + fixture["heldout"]:
        state, _ = models.make_state(case["text"])
        assert "expected" not in state
        models.validate_decision(dict(zip(models.FIELDS, case["expected"])), models.questions_for(state))


def test_unique_cancellable_order_ignores_closed_history():
    """同票号终态历史不等于多个取消目标；第二张可取消单或不完整分页必须阻止取消。"""
    # 历史终态与当前可取消单同时存在是正常业务情况，不能与多张可取消单混为一谈。
    current = {"refundSerialNo": "refund-a", "refundState": "PENDING_APPLY", "gds": "Amadeus"}
    history = {"refundSerialNo": "refund-b", "refundState": "REFUND_DONE", "gds": "Amadeus"}
    output = {"list": {"totalCount": 2, "pageList": [current, history]}}
    assert qa.eligible_refund(output, "refund-a") == current
    history["refundState"] = "REFUND_FAIL"
    with pytest.raises(ValueError, match="not_unique"):
        qa.eligible_refund(output, "refund-a")
    output["list"]["totalCount"] = 3
    with pytest.raises(ValueError, match="incomplete"):
        qa.eligible_refund(output, "refund-a")


def test_readback_requires_identity_state_and_ticket():
    """读回成功只有在退票身份、票号关联和取消状态同时匹配时才成立。"""
    # 逐一破坏身份、票号或状态，防止仅根据success/取消枚举判成功。
    output = {"success": True, "saasRefundOrderVO": {"refundSerialNo": "refund-a", "refundState": "REFUND_CANCEL",
                                                    "psis": [{"item": {"ticketNo": "ticket-a"}}]}}
    assert qa.verified_readback(output, "refund-a", "ticket-a")
    assert not qa.verified_readback(output, "refund-b", "ticket-a")
    assert not qa.verified_readback(output, "refund-a", "ticket-b")
    output["saasRefundOrderVO"]["refundState"] = "PENDING_APPLY"
    assert not qa.verified_readback(output, "refund-a", "ticket-a")


def test_nonexecution_decision_cannot_call_business(monkeypatch):
    """模型选择仅咨询时不触发任何业务调用，即使存在真实准备订单。"""
    # 替身显式拒绝任何业务调用，直接验证咨询意图的边界。
    def decision(*args):
        """返回预设咨询决策，替代外部模型调用。"""
        return {"ok": True, "decision": {"intent": "cancel_refund", "action": "inquire", "target": "t1", "reason": "automatic"}}

    def no_record(request_id):
        """本例没有历史写执行，返回None。"""
        return None

    def forbidden(*args):
        """业务调用属于测试失败，明确拒绝派发。"""
        pytest.fail("non-execution decision dispatched business call")

    monkeypatch.setattr(qa, "measure", decision)
    monkeypatch.setattr(qa, "known_execution", no_record)
    monkeypatch.setattr(qa, "execute", forbidden)
    report = qa.run_one("jev", {"ticket": "TTT4102161000018", "refund_no": "refund-a"}, "test-slot", Path("unused"))
    assert not report["verified"]
    assert report["error_code"] == "model_did_not_select_supported_request"


def test_unknown_cancel_is_observed_without_second_write(monkeypatch):
    """写入响应丢失后只查执行记录与详情，不以新ID重复取消且保留测量失败。"""
    # 故障发生在写入派发后，恢复必须观察事实而不是重复提交。
    calls = []
    ticket = "TTT4102161000018"
    def decision(*args):
        """返回有效闭集决策，使流程进入取消阶段。"""
        return {"ok": True, "decision": {"intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic"}}

    def record(request_id):
        """模拟服务在取消派发后留下的持久记录。"""
        return {"execution_id": "record-a", "status": "running"} if "cancel" in calls else None

    def operation(action, arguments, request_id):
        """模拟查询、丢失响应的写入和随后成功的业务状态观察。"""
        # 只在取消阶段丢失响应，后续读取仍能观察已落地的业务状态。
        calls.append(action)
        if action == "queryList":
            return {"list": {"totalCount": 1, "pageList": [{"refundSerialNo": "refund-a", "refundState": "PENDING_APPLY", "gds": "Amadeus"}]}}, {"elapsed_ms": 1}
        if action == "cancel":
            raise TimeoutError("lost response")
        return {"saasRefundOrderVO": {"refundSerialNo": "refund-a", "refundState": "REFUND_CANCEL", "psis": [{"item": {"ticketNo": ticket}}]}}, {"elapsed_ms": 1}

    monkeypatch.setattr(qa, "measure", decision)
    monkeypatch.setattr(qa, "known_execution", record)
    monkeypatch.setattr(qa, "execute", operation)
    report = qa.run_one("jev", {"ticket": ticket, "refund_no": "refund-a"}, "test-slot", Path("unused"))
    assert calls == ["queryList", "cancel", "queryDetailByRefundNo"]
    assert report["diagnostic_cancelled"]
    assert not report["verified"]
    assert report["error_type"] == "TimeoutError"


def test_report_cannot_recommend_from_missing_or_duplicate_samples(tmp_path):
    """只有完整独立样例和九个已验证槽位才允许建议接入；重复行不能补足缺失样例。"""
    heldout = tmp_path / "heldout"
    heldout.mkdir()
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    samples = [{"id": f"sample-{i}"} for i in range(20)]
    metadata = {"fixture_cases": samples, "repeats": 3, "rubric": models.RUBRIC, "contract": models.CONTRACT}
    (heldout / "inputs.json").write_text(json.dumps(metadata))
    rows = [{"arm": arm, "sample_id": sample["id"], "repeat": repeat, "ok": True,
             "correct": True, "unsafe_route": False, "unresolved": False,
             "client_ms": 100 if arm == "jev" else 1000}
            for arm in models.ARMS for sample in samples for repeat in (1, 2, 3)]
    for slot in range(9):
        (qa_root / f"qa-{slot + 1}.json").write_text(json.dumps(
            {"slot": slot + 1, "arm": models.ARMS[slot % 3], "verified": True,
             "workflow_ms": 100, "business_ms": 50}))
    # 先证明有效完整实验可通过，再替换一条Jev测量为重复结果验证拒绝逻辑。
    measurements = heldout / "samples.jsonl"
    measurements.write_text("\n".join(json.dumps(row) for row in rows))
    assert models.write_report(tmp_path)["recommend_jev_integration"]
    rows[1] = rows[0]
    measurements.write_text("\n".join(json.dumps(row) for row in rows))
    verdict = models.write_report(tmp_path)
    assert not verdict["heldout_complete"]
    assert not verdict["recommend_jev_integration"]
