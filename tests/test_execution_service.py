import json
from pathlib import Path

from ai_test_platform.execution import (
    AssertionEngine,
    ExecutionService,
    JsonParseError,
    parse_stdout_json,
    resolve_value,
)


def test_assertion_engine_reports_nested_differences():
    engine = AssertionEngine()

    result = engine.assert_json(
        {
            "success": True,
            "order": {"status": "支付中", "amount": 42},
            "items": ["adult", "child"],
        },
        {
            "success": True,
            "order.status": "已支付",
            "order.amount": {"op": "gte", "value": 40},
            "items": {"op": "contains", "value": "child"},
            "missing": "null",
        },
    )

    assert result["passed"] is False
    assert result["diffs"] == [
        {
            "path": "order.status",
            "expected": "已支付",
            "actual": "支付中",
            "operator": "eq",
        }
    ]


def test_resolve_value_uses_previous_step_outputs():
    outputs = [
        {"orderSerialId": "HTKB20260525001"},
        {"nested": {"transactionId": "TX001"}},
    ]

    assert resolve_value("${steps[0].output.orderSerialId}", outputs) == "HTKB20260525001"
    assert (
        resolve_value("txn-${steps[1].output.nested.transactionId}", outputs)
        == "txn-TX001"
    )


def test_parse_stdout_json_accepts_last_json_block():
    parsed = parse_stdout_json("debug line\n{\"success\": true, \"count\": 1}\n")

    assert parsed == {"success": True, "count": 1}


def test_parse_stdout_json_raises_for_missing_json():
    try:
        parse_stdout_json("plain text only")
    except JsonParseError as exc:
        assert "stdout" in str(exc)
    else:
        raise AssertionError("expected JsonParseError")


def test_execution_service_records_command_stdout_and_assertion_diff(tmp_path: Path):
    script = tmp_path / "status.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' '{\"success\":true,\"orderStatus\":\"支付中\"}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    steps = [
        {
            "step_index": 1,
            "name": "验证支付结果",
            "execution_type": "script",
            "execution_tool": "tool://facade.order.query_detail",
            "input_params": {"order-serial-no": "HTKB20260525001"},
            "verification_type": "assertion",
            "verification_assertion": {
                "success": True,
                "orderStatus": "已支付",
            },
        }
    ]
    (case_dir / "steps.json").write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")

    service = ExecutionService(data_root=tmp_path)
    result = service.run_steps(
        steps_file=case_dir / "steps.json",
        tool_index={
            "facade.order.query_detail": {
                "script_path": str(script),
                "display_name": "订单查询接口 - 查询详情",
            }
        },
        cli_dir=tmp_path,
        skill_dir=tmp_path,
        run_dir=tmp_path / "runs" / "run-test",
        binding={
            "snapshot_id": "S20260525-001",
            "case_version": "case-v1",
            "cli_version": "cli-v1",
            "knowledge_version": "kb-v1",
        },
    )

    assert result["status"] == "failed"
    assert result["llm_invocations"] == 0
    assert result["steps"][0]["stdout_json"] == {"success": True, "orderStatus": "支付中"}
    assert result["steps"][0]["assertion_result"]["diffs"][0] == {
        "path": "orderStatus",
        "expected": "已支付",
        "actual": "支付中",
        "operator": "eq",
    }
    assert "--order-serial-no" in result["steps"][0]["command"]
