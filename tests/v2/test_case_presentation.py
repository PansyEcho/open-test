"""验证Case展示的局部序列化与纯前端业务适配，不访问QA。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from opentest.api import create_app
from opentest.domain.case_template_v4 import CaseGenerationExecutionV4


@pytest.mark.parametrize("value", [None, {}, [], "", 0, False])
def test_execution_get_preserves_recorded_values_and_absence(value) -> None:
    """执行GET保留所有显式值，旧记录缺失字段不被模型默认值补出。

    Args:
        value: 每个需要与字段缺失区分的JSON值。
    Returns:
        None；列表和详情一致保留存在性，既有模型完整序列化不受影响时通过。
    """
    # 模拟磁盘原始JSON经过现有严格模型回读，而不是构造已补齐默认值的结果。
    payload = {
        "execution_id": "case-generation-execution-" + "a" * 20,
        "generation_id": "case-template-generation-" + "b" * 20,
        "system_id": "sample.java.system", "environment_id": "qa", "status": "PASSED",
        "variant_results": [{
            "variant_id": "case-variant-v4-" + "c" * 20, "status": "COMPLETED",
            "operations": [
                {"stage_id": "target", "function_id": "facade:sample", "status": "COMPLETED", "actual_response": value},
                {"stage_id": "oracle:old", "function_id": "facade:sample", "status": "COMPLETED"},
            ],
            "assertions": [
                {"oracle_id": "response", "actual_path": "value", "operator": "eq", "expected_value": value, "actual_value": value, "passed": True},
                {"oracle_id": "old", "actual_path": "value", "operator": "eq", "passed": True},
            ],
        }],
    }
    execution = CaseGenerationExecutionV4.model_validate_json(json.dumps(payload))
    application = Mock()
    application.get_case_generation_execution.return_value = execution
    application.list_case_generation_executions.return_value = [execution]
    client = TestClient(create_app(application))
    for suffix in ("", "/" + execution.execution_id):
        response = client.get("/api/v2/systems/sample.java.system/case-executions" + suffix)
        assert response.status_code == 200
        body = response.json()
        record = body["execution"] if suffix else body["executions"][0]
        result = record["variant_results"][0]
        assert "actual_response" in result["operations"][0]
        assert result["operations"][0]["actual_response"] == value
        assert "actual_response" not in result["operations"][1]
        assert result["assertions"][0]["actual_value"] == value
        assert "actual_value" not in result["assertions"][1]
        assert "expected_value" not in result["assertions"][1]
    # 修改限定GET，不改变存储及直接模型消费者的既有默认值规则。
    assert "actual_response" in execution.model_dump()["variant_results"][0]["operations"][1]


def test_case_view_business_adapters() -> None:
    """使用Node标准测试器执行纯展示规则的反例测试，不安装浏览器或新依赖。

    Returns:
        None；所有值、状态、历史和变化来源断言通过时结束。
    Raises:
        CalledProcessError: 任一前端业务适配断言失败。
    """
    # 通过仓库现有pytest统一入口调度Node，验证业务语义而非字符串快照。
    test_path = Path(__file__).parents[1] / "web" / "case-view.test.js"
    subprocess.run(["node", "--test", str(test_path)], check=True, capture_output=True, text=True)
