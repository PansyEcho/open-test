"""验证任务MCP下游检索固定来源范围且不授予QA执行权限。"""

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from opentest.api import create_app
from opentest.application.downstream_interfaces import DownstreamInterfaceSearchService
from test_web_generation import _application, TASK_ID


@pytest.mark.parametrize("operation", ["case-generation", "contract-completion", "data-capability-generation"])
def test_task_downstream_search_uses_frozen_handoff_scope(tmp_path, monkeypatch, operation):
    """三种生成任务共用只读检索，调用方不能通过HTTP替换冻结scan。

    Args:
        tmp_path: 隔离的任务与Case handoff存储。
        monkeypatch: 替换依赖资料读取边界，避免访问本机Maven目录。
        operation: Case、契约或共享数据任务。
    Returns:
        None；工具公开、固定scope被传入且返回结果不授予执行能力时通过。
    """

    application, handoff = _application(tmp_path)
    search = Mock(return_value={"interfaces": [{"method_name": "query", "executable": False}], "gaps": []})
    monkeypatch.setattr(DownstreamInterfaceSearchService, "search_page", search)
    if operation != "case-generation":
        # 使用各任务真实的绑定选择逻辑；资料读取不属于本接线测试的范围。
        task = application.tasks.get(TASK_ID).model_copy(update={"operation": operation})
        monkeypatch.setattr(application.tasks, "get", Mock(return_value=task))
        application.data_capabilities = SimpleNamespace(
            agent_tools=Mock(return_value=[]), _handoff=Mock(return_value=handoff),
        )
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        tools = client.get(f"/api/v2/tasks/{TASK_ID}/agent-tools").json()["tools"]
        tool = next(item for item in tools if item["name"] == "search_downstream_interfaces")
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["inputSchema"]["additionalProperties"] is False
        response = client.post(f"/api/v2/tasks/{TASK_ID}/agent-tools/search_downstream_interfaces", json={
            "downstream_system": "dsf.booking.core", "query": "query", "limit": 5,
        })
        assert response.status_code == 200
        assert response.json()["result"]["interfaces"][0]["executable"] is False
        assert search.call_args.args[:2] == (handoff.system_id, handoff.source_scopes)
        assert search.call_args.args[2].model_dump() == {"downstream_system": "dsf.booking.core", "query": "query", "limit": 5, "offset": 0}
    finally:
        application.close()


@pytest.mark.parametrize("extra", [{"source_scopes": []}, {"path": "/tmp/other"}, {"limit": True}, {"limit": 51}])
def test_task_downstream_search_rejects_scope_injection_and_unbounded_request(tmp_path, monkeypatch, extra):
    """直接HTTP调用也不能改变来源或绕过有界结果数。

    Args:
        tmp_path: 隔离任务和handoff目录。
        monkeypatch: 记录资料读取是否发生。
        extra: 越界参数或非合法整型结果数。
    Returns:
        None；非法请求在读取下游资料前被拒绝时通过。
    """

    application, _ = _application(tmp_path)
    search = Mock()
    monkeypatch.setattr(DownstreamInterfaceSearchService, "search_page", search)
    client = TestClient(create_app(application), client=("127.0.0.1", 50000))
    try:
        # 服务端校验不依赖MCP客户端遵守JSON Schema。
        response = client.post(f"/api/v2/tasks/{TASK_ID}/agent-tools/search_downstream_interfaces", json={
            "downstream_system": "dsf.booking.core", **extra,
        })
        assert response.status_code == 400
        search.assert_not_called()
    finally:
        application.close()
