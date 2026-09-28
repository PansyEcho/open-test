"""验证十秒入口实验的真实目标绑定、调用边界及错误观察，不调用外部模型或QA。"""

import json
from pathlib import Path
import select
import subprocess
import sys

import pytest

from scripts import benchmark_refund_entry as entry
from scripts import prepare_refund_entry_data as preparation


def job(arm="http-jev"):
    """返回包含故意错误准备单号的合成任务，验证执行目标只能来自实时查询。"""
    return {"arm": arm, "sample_id": "sample-01-" + arm, "request_id": "entry-unit-01",
            "user_request": "取消TTT4102161000018的退票单，原因自动填写。",
            "expected_refund": "preparation-must-not-select-target"}


def test_short_qa_tickets_require_explicit_ticket_label():
    """真实QA短票号只在明确票号字段后成为候选，其他日期、数量不能意外成为业务目标。"""
    state, mapping = entry.models.make_state("2026年9月取消票号是123456，数量123；另查票号为789。")
    assert mapping == {"t1": "123456", "t2": "789"}
    assert "2026" in state["user_request"]
    assert "数量123" in state["user_request"]
    assert "票号是TICKET_1" in state["user_request"]


def install_business(monkeypatch, calls, lose_cancel=False):
    """安装带身份校验和可选丢失取消响应的服务替身；calls记录实际派发顺序。"""
    def record(request_id):
        """写请求派发后才存在记录，模拟未知写入的既有去重证据。"""
        return {"status": "completed"} if "cancel" in calls else None

    def preflight():
        """模拟QA环境和操作契约检查成功，不访问网络。"""
        return None

    def execute(action, arguments, request_id):
        """返回真实关联的合成结果；取消时检查单号来源，并可模拟响应丢失。"""
        calls.append(action)
        if action == "queryList":
            assert arguments["ticketNo"] == "TTT4102161000018"
            output = {"list": {"totalCount": 1, "pageList": [
                {"refundSerialNo": "from-live-query", "refundState": "PENDING_APPLY", "gds": "Amadeus"}]}}
        elif action == "cancel":
            assert arguments["refundSerialNo"] == "from-live-query"
            if lose_cancel:
                raise TimeoutError("response lost")
            output = {"success": True}
        else:
            output = {"saasRefundOrderVO": {"refundSerialNo": "from-live-query", "refundState": "REFUND_CANCEL",
                                           "psis": [{"item": {"ticketNo": "TTT4102161000018"}}]}}
        return output, {"action": action, "elapsed_ms": 10, "request_id": request_id}

    def measure(arm, text, key_file):
        """返回固定的单目标自动原因决策，避免单测依赖模型网络。"""
        return {"ok": True, "client_ms": 1, "decision": {
            "intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic"}}

    monkeypatch.setattr(entry.qa, "known_execution", record)
    monkeypatch.setattr(entry.qa, "preflight", preflight)
    monkeypatch.setattr(entry.qa, "execute", execute)
    monkeypatch.setattr(entry.models, "measure", measure)


def test_fast_workflow_uses_queried_identity_and_three_stages(monkeypatch):
    """准备单号不能决定目标，查询、取消、真实详情回查必须按序发生。"""
    calls = []
    install_business(monkeypatch, calls)
    workflow = entry.RefundWorkflow(job(), Path("unused"))
    report = workflow.run_fast()
    assert report["verified"]
    assert calls == ["queryList", "cancel", "queryDetailByRefundNo"]
    assert report["business_ms"] == 30
    assert report["workflow_ms"] >= report["preflight_ms"]


@pytest.mark.parametrize("field,choice", [("action", "refrain"), ("action", "inquire"),
                                          ("target", "ambiguous"), ("target", "none"),
                                          ("intent", "cancel_booking"), ("reason", "unspecified")])
def test_nonexecution_choices_do_not_access_business(monkeypatch, field, choice):
    """否定、咨询、多目标、缺目标、取消原订单和未授权原因均不能触发业务调用。"""
    calls = []
    install_business(monkeypatch, calls)

    def measure(arm, text, key_file):
        """在有效结构中替换当前反例字段，返回不可执行或不支持的决策。"""
        decision = {"intent": "cancel_refund", "action": "execute", "target": "t1", "reason": "automatic"}
        decision[field] = choice
        return {"ok": True, "decision": decision}

    monkeypatch.setattr(entry.models, "measure", measure)
    report = entry.RefundWorkflow(job(), Path("unused")).run_fast()
    assert report["outcome"] == "not_executed"
    assert not report["verified"]
    assert not calls


def test_lost_write_is_observed_and_never_replayed(monkeypatch):
    """取消响应未知时只读查证；即使事实已取消，也保留此次失败，不变成速度成功样本。"""
    calls = []
    install_business(monkeypatch, calls, lose_cancel=True)
    report = entry.RefundWorkflow(job(), Path("unused")).run_fast()
    assert calls == ["queryList", "cancel", "queryDetailByRefundNo"]
    assert report["diagnostic_cancelled"]
    assert not report["verified"]
    assert report["outcome"] == "failed"


def test_new_instance_recovers_binding_from_existing_query(monkeypatch):
    """新实例遇到已有未知写入时，从同前缀查询恢复身份并只读回查，仍不计为新成功样本。"""
    calls = []
    install_business(monkeypatch, calls)

    def record(request_id):
        """提供不含arguments的真实记录结构，查询记录保存当时唯一可取消目标。"""
        if request_id.endswith("-cancel"):
            return {"status": "running"}
        return {"result": {"output": {"list": {"totalCount": 1, "pageList": [
            {"refundSerialNo": "from-live-query", "refundState": "PENDING_APPLY", "gds": "Amadeus"}]}}}}

    monkeypatch.setattr(entry.qa, "known_execution", record)
    execute = entry.qa.execute
    observed_ids = []

    def fresh_observation(action, arguments, request_id):
        """即使新建第二实例，诊断也必须取得新只读观察而非命中首次旧结果。"""
        assert request_id not in observed_ids
        observed_ids.append(request_id)
        return execute(action, arguments, request_id)

    monkeypatch.setattr(entry.qa, "execute", fresh_observation)
    entry.RefundWorkflow(job(), Path("unused")).run_fast()
    report = entry.RefundWorkflow(job(), Path("unused")).run_fast()
    assert calls == ["queryDetailByRefundNo", "queryDetailByRefundNo"]
    assert report["diagnostic_cancelled"]
    assert not report["verified"]
    assert report["error_code"] == "prior_write_requires_readonly_inspection"


@pytest.mark.parametrize("parent_exits", [False, True])
def test_agent_cleanup_removes_mcp_descendant(parent_exits):
    """独立进程组清理覆盖父进程存活和已退出两种情况，不留下忽略TERM的MCP替身。"""
    child_code = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    parent_code = ("import subprocess,sys,time;"
                   f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
                   "print(child.pid,flush=True);" + ("sys.exit(0)" if parent_exits else "time.sleep(60)"))
    process = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, start_new_session=True)
    try:
        assert int(process.stdout.readline()) > 0
        if parent_exits:
            process.wait(timeout=3)
        entry.stop_agent_group(process)
        # MCP替身继承stdout写端；只有父子都退出/关闭后，读端才会EOF，无需访问系统进程表。
        assert select.select([process.stdout], [], [], 2)[0], "MCP descendant still holds output pipe"
        assert process.stdout.read() == b""
    finally:
        entry.stop_agent_group(process)
        process.stdout.close()


def test_atomic_tools_require_query_and_cannot_select_other_ticket(monkeypatch):
    """模型不能猜测退票候选或改用不存在的票号候选，聚合工具也不出现在原子路径中。"""
    calls = []
    install_business(monkeypatch, calls)
    workflow = entry.RefundWorkflow(job("codex-atomic"), Path("unused"))
    with pytest.raises(ValueError, match="verified_query"):
        entry.dispatch_tool(workflow, "cancel_refund", {"refund_candidate": "r1"})
    with pytest.raises(ValueError, match="unknown_ticket"):
        entry.dispatch_tool(workflow, "query_refund", {"ticket_candidate": "t2"})
    with pytest.raises(ValueError, match="not_in_arm"):
        entry.dispatch_tool(workflow, "execute_refund_request", {"user_request": workflow.state["user_request"]})
    assert not calls


def test_aggregate_tool_preserves_original_request(monkeypatch):
    """Codex不得先改写用户请求再交给Jev，模型可见结果不包含真实业务标识。"""
    workflow = entry.RefundWorkflow(job("codex-jev"), Path("unused"))
    observed = []

    def invoke(prepared):
        """捕获本机HTTP收到的原始请求，并模拟已完成的真实业务证据。"""
        observed.append(prepared["user_request"])
        return {"verified": True, "workflow_ms": 7000, "outcome": "verified"}

    monkeypatch.setattr(entry, "call_entry", invoke)
    with pytest.raises(ValueError, match="original_request_changed"):
        entry.dispatch_tool(workflow, "execute_refund_request", {"user_request": "取消所有订单"})
    output = entry.dispatch_tool(workflow, "execute_refund_request", {"user_request": workflow.state["user_request"]})
    assert observed == [workflow.job["user_request"]]
    assert "TTT4102161000018" not in json.dumps(output)
    assert output["verified"]


def test_readback_cannot_hide_wrong_ticket(monkeypatch):
    """最后详情的身份校验失败必须使完整流程失败，不能由取消接口成功覆盖。"""
    calls = []
    install_business(monkeypatch, calls)

    def reject(output, refund_no, ticket):
        """模拟回查身份或状态不符，返回未验证。"""
        return False

    monkeypatch.setattr(entry.qa, "verified_readback", reject)
    report = entry.RefundWorkflow(job(), Path("unused")).run_fast()
    assert not report["verified"]
    assert report["error_code"] == "readback_failed"


def test_report_keeps_slow_and_failed_requests(tmp_path):
    """十秒分母包含慢调用和失败，报告不得把内部流程耗时当成完整Agent耗时。"""
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    (qa_root / "qa-inputs.json").write_text(json.dumps({"preparation_ms": 1000}))
    for index, (arm, elapsed, verified) in enumerate([
            ("codex-jev", 22000, True), ("codex-jev", 100, False), ("http-jev", 7000, True)]):
        directory = tmp_path / f"sample-{index:02}-{arm}"
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps({
            "arm": arm, "sample_id": directory.name, "entry_ms": elapsed, "verified": verified}))
        (directory / "workflow.json").write_text(json.dumps({"workflow_ms": 6500}))
    entry.write_report(tmp_path)
    summary = json.loads((tmp_path / "comparison.json").read_text())
    assert summary["codex-jev"]["count"] == 2
    assert summary["codex-jev"]["within_10s"] == 0
    assert summary["http-jev"]["within_10s"] == 1
    assert "22.000s" in (tmp_path / "report.md").read_text()


def booking_fixture():
    """构造含护照、可选空值和DSF浮点整数的单票出票详情，不包含真实乘客资料。"""
    passenger = {"passengerId": "passenger-1", "passengerType": "ADT", "gender": "M", "creditType": "PP",
                 "lastName": "TEST", "firstName": "USER", "creditNo": "synthetic", "birthday": "1990-01-01",
                 "nationCode": "CN", "gmtCreditValidate": "2030-01-01 00:00:00.000000"}
    segment = {field: "synthetic" for field in (
        "flightNo", "departureCityCode", "departureCity", "arrivalCityCode", "arrivalCity",
        "departureAirportCode", "departureAirport", "arrivalAirportCode", "arrivalAirport", "carrier", "realCarrier")}
    segment.update(sequence=1.0, carrierName=None, segmentId="segment-1",
                   gmtTakeOff="2026-10-01 12:00:00.000000", gmtArrive="2026-10-01 14:00:00.000000")
    return {"orderSerialNo": "booking-1", "memberId": "member-1", "orderChannelSource": 8.0,
            "orderState": "TICKETED", "gds": "Amadeus",
            "psis": [{"passenger": passenger, "segment": segment, "item": {"ticketNo": "123456"}}]}


def test_preparation_preserves_real_enum_and_identity():
    """创建请求保留真实乘客和航段，仅按已验证枚举及整数契约转换格式。"""
    order = booking_fixture()
    psi = preparation.verified_booking_v1(order, [{"refundState": "REFUND_CANCEL"}], {"totalCount": 0, "pageList": []})
    request = preparation.create_request_v1(order, psi)
    passenger = request["refundDetailApiDTO"]["refundItemInfos"][0]["passenger"]
    segment = request["refundDetailApiDTO"]["segmentRefundInfos"][0]
    assert passenger["gender"] == 1 and passenger["creditType"] == 1
    assert passenger["creditNo"] == "synthetic"
    assert request["passengerIds"] == ["passenger-1"]
    assert type(request["orderChannelSource"]) is int
    assert type(segment["sequence"]) is int and "carrierName" not in segment


@pytest.mark.parametrize("unsafe", ["active_refund", "change", "unsupported_credit", "fractional_channel"])
def test_preparation_rejects_unverified_business_conditions(unsafe):
    """活动退票、改签、未登记证件类型和非整数渠道均不能被转换或伪造为可用数据。"""
    order = booking_fixture()
    refunds = [{"refundState": "PENDING_APPLY"}] if unsafe == "active_refund" else []
    changes = {"totalCount": 1, "pageList": [{}]} if unsafe == "change" else {"totalCount": 0, "pageList": []}
    if unsafe == "unsupported_credit":
        order["psis"][0]["passenger"]["creditType"] = "ID"
    if unsafe == "fractional_channel":
        order["orderChannelSource"] = 8.5
    with pytest.raises(ValueError):
        psi = preparation.verified_booking_v1(order, refunds, changes)
        preparation.create_request_v1(order, psi)


def test_preparation_observes_lost_create_without_replay(monkeypatch):
    """创建响应丢失后只查已有记录和真实新单；不能以重发写请求解决未知结果。"""
    order = booking_fixture()
    writes = []
    reads = []

    def find(prefix):
        """返回已验证的合成出票关系，隔离外部数据搜索。"""
        return order, order["psis"][0]

    def known(request_id):
        """模拟提交后仍无终态记录，必须保留准备失败。"""
        return None

    def create(method, path, payload):
        """记录唯一创建请求后模拟连接中断。"""
        writes.append(payload["request_id"])
        raise TimeoutError("lost response")

    def execute(action, arguments, request_id):
        """提供已创建的真实关联详情，证明读成功也不能覆盖未知创建执行。"""
        reads.append(action)
        if action == "queryList":
            return {"list": {"totalCount": 1, "pageList": [{"refundSerialNo": "new-refund", "refundState": "PENDING_APPLY"}]}}, {}
        return {"saasRefundOrderVO": {"refundSerialNo": "new-refund", "orderSerialNo": "booking-1",
                                      "refundState": "PENDING_APPLY", "psis": [{"item": {"ticketNo": "123456"}}]}}, {}

    monkeypatch.setattr(preparation, "find_booking_v1", find)
    monkeypatch.setattr(preparation.qa, "known_execution", known)
    monkeypatch.setattr(preparation.qa, "api_call", create)
    monkeypatch.setattr(preparation.qa, "execute", execute)
    with pytest.raises(ValueError, match="create_outcome_requires_inspection"):
        preparation.prepare_refund_entry_v1("create-unit")
    assert writes == ["create-unit-create"]
    assert reads == ["queryList", "queryDetailByRefundNo"]


def test_preparation_recovery_reads_fresh_state_without_new_create(monkeypatch):
    """首次观察未落地、第二次创建完成时必须使用新只读键；稳定创建键不能再次写入。"""
    order = booking_fixture()
    writes = []
    read_ids = []
    record = {"status": "running"}

    def find(prefix):
        """模拟同一准备请求的原始候选记录，保持写入身份不变。"""
        return order, order["psis"][0]

    def known(request_id):
        """创建派发后始终返回已有记录，随后由测试将其推进到成功终态。"""
        return record if writes else None

    def create(method, path, payload):
        """只允许一次创建，首次结果仍运行中。"""
        writes.append(payload["request_id"])
        return {"execution": record}

    def execute(action, arguments, request_id):
        """服务读结果按request ID冻结，因此恢复必须发起新的观察键。"""
        assert request_id not in read_ids
        read_ids.append(request_id)
        if action == "queryList":
            orders = [] if record["status"] == "running" else [{"refundSerialNo": "new-refund", "refundState": "PENDING_APPLY"}]
            return {"list": {"totalCount": len(orders), "pageList": orders}}, {}
        return {"saasRefundOrderVO": {"refundSerialNo": "new-refund", "orderSerialNo": "booking-1",
                                      "refundState": "PENDING_APPLY", "psis": [{"item": {"ticketNo": "123456"}}]}}, {}

    monkeypatch.setattr(preparation, "find_booking_v1", find)
    monkeypatch.setattr(preparation.qa, "known_execution", known)
    monkeypatch.setattr(preparation.qa, "api_call", create)
    monkeypatch.setattr(preparation.qa, "execute", execute)
    with pytest.raises(ValueError, match="created_refund_not_unique"):
        preparation.prepare_refund_entry_v1("recovery-unit")
    record.update(status="completed", execution_id="create-execution", result={"status": "success", "output": {"success": True}})
    prepared = preparation.prepare_refund_entry_v1("recovery-unit")
    assert prepared["refund_no"] == "new-refund"
    assert writes == ["recovery-unit-create"]


def test_prepared_slot_recovers_job_after_interrupted_save(tmp_path, monkeypatch):
    """准备记录已落盘而job尚未保存时，同一槽位恢复不能再次造数或增加准备统计。"""
    directory = tmp_path / "sample-01-http-jev"
    directory.mkdir()
    (tmp_path / "qa").mkdir()
    job_path = directory / "job.json"
    entry.save_json(job_path, {"sample_id": directory.name, "request_id": "recover-slot", "request_template": "取消票号{ticket}的退票单"})
    inputs_path = tmp_path / "qa/qa-inputs.json"
    entry.save_json(inputs_path, {"orders": [{"sample_id": directory.name, "refund_no": "prepared-refund",
                                            "ticket": "123456", "preparation_ms": 100}], "preparation_ms": 100})

    def forbid_create(prefix):
        """已准备槽位不能再调用造数接口。"""
        pytest.fail("already prepared slot must not create again")

    monkeypatch.setattr(preparation, "prepare_refund_entry_v1", forbid_create)
    restored = entry.prepare_job(job_path)
    assert restored["expected_refund"] == "prepared-refund"
    assert restored["user_request"] == "取消票号123456的退票单"
    assert json.loads(inputs_path.read_text())["preparation_ms"] == 100
