"""用真实任务模型离线验证网页提示，不因默认 HTTP 应用需要 MySQL 而跳过。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opentest.application.web_generation import WebGenerationService
from opentest.domain.models import TaskRecord


@pytest.mark.parametrize("environment_id", [None, "qa", "uat"])
@pytest.mark.parametrize("supplement", [False, True])
def test_case_prompt_reads_frozen_environment_from_real_task(environment_id, supplement):
    """真实TaskRecord的普通和补充提示均可生成；新任务使用冻结环境，旧任务缺环境时沿用QA。

    Args:
        environment_id: 已冻结环境，None模拟旧任务未保存该字段。
        supplement: 是否已有绑定当前任务的覆盖缺口。
    Returns:
        None；提示可达且覆盖读取没有越过任务固定环境时通过。
    """

    task = TaskRecord(task_id="task-" + "1" * 16, operation="case-generation", system_id="refund",
        generation_id="generation-fixed", trace_id="prompt-offline",
        result={} if environment_id is None else {"environment_id": environment_id})
    coverage = Mock()
    # 隔离持久层与模型，只以真实TaskRecord经过生产提示入口，防止宽松Mock掩盖不存在的属性。
    coverage.projection.return_value = {"supplement_task_id": task.task_id, "gaps": [
        {"gap_id": "gap-query", "kind": "METHOD", "location": {"class_name": "Query"}}]} if supplement else None
    service = object.__new__(WebGenerationService)
    service.application = SimpleNamespace(coverage_assistance=coverage)

    prompt = service._analysis_prompt(task)

    coverage.projection.assert_called_once_with("refund", "generation-fixed", environment_id or "qa")
    assert task.task_id in prompt and "search_data_capabilities" in prompt
    if supplement:
        assert prompt.startswith("本轮是覆盖缺口补充任务")
        assert "gap-query" in prompt and "coverage_dispositions" in prompt
    else:
        assert prompt.startswith("完成当前OpenTest Case生成任务")
