"""验证OpenTest通过同用户本机IPC把turn启动交给Codex桌面owner。"""

from __future__ import annotations

import json
import socket
import struct
import tempfile
import threading
from pathlib import Path
from typing import Any

from opentest.adapters.codex_desktop import CodexDesktopBridge, CodexDesktopBridgeConfig


def _read_frame(connection: socket.socket) -> dict[str, Any]:
    """从测试Unix连接读取一个四字节小端长度前缀JSON对象。

    Args:
        connection: Codex桌面桥接创建的本机短连接。

    Returns:
        已解析的IPC请求对象。

    Raises:
        AssertionError: 连接提前关闭或请求不是JSON对象。
    """

    # 测试服务端也按生产wire逐段读取，避免一次recv恰好返回完整帧造成伪通过。
    header = _read_exact(connection, 4)
    payload_length = struct.unpack("<I", header)[0]
    payload = json.loads(_read_exact(connection, payload_length).decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _read_exact(connection: socket.socket, expected_bytes: int) -> bytes:
    """读取测试帧当前阶段要求的精确字节数。

    Args:
        connection: 已接受的本机Unix连接。
        expected_bytes: 帧头或帧体需要读取的字节数。

    Returns:
        长度严格匹配的字节串。

    Raises:
        AssertionError: 对端在完整帧到达前关闭连接。
    """

    chunks: list[bytes] = []
    remaining = expected_bytes
    while remaining:
        chunk = connection.recv(remaining)
        assert chunk
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_frame(connection: socket.socket, payload: dict[str, Any]) -> None:
    """向测试客户端写回一个符合桌面IPC格式的JSON响应。

    Args:
        connection: 已接受的本机Unix连接。
        payload: 与请求ID绑定的模拟路由响应。

    Side Effects:
        向Unix连接发送一个完整长度前缀帧。
    """

    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    connection.sendall(struct.pack("<I", len(encoded)) + encoded)


def _serve_desktop_owner(
    listener: socket.socket,
    requests: list[dict[str, Any]],
    follower_error: str = "",
) -> None:
    """模拟IPC路由和已打开原线程的Codex桌面owner。

    Args:
        listener: 已绑定并监听的同用户Unix套接字。
        requests: 用于断言协议版本、身份和载荷的请求收集器。
        follower_error: 可选的follower阶段固定错误代码。

    Side Effects:
        接受一次短连接，依次回复initialize、owner discovery和follower start-turn。
    """

    connection, _ = listener.accept()
    with connection:
        for index in range(3):
            request = _read_frame(connection)
            requests.append(request)
            if index == 0:
                result = {"clientId": "opentest-client"}
                response = {
                    "type": "response",
                    "requestId": request["requestId"],
                    "resultType": "success",
                    "method": "initialize",
                    "handledByClientId": "opentest-client",
                    "result": result,
                }
            elif index == 1:
                response = {
                    "type": "response",
                    "requestId": request["requestId"],
                    "resultType": "success",
                    "method": "thread-owner-discovery",
                    "handledByClientId": "desktop-owner",
                    "result": {},
                }
            elif follower_error:
                # 协议版本变化必须直接反馈手动操作，测试owner不会收到任何降级App Server写入。
                response = {
                    "type": "response",
                    "requestId": request["requestId"],
                    "resultType": "error",
                    "error": follower_error,
                }
            else:
                response = {
                    "type": "response",
                    "requestId": request["requestId"],
                    "resultType": "success",
                    "method": "thread-follower-start-turn",
                    "handledByClientId": "desktop-owner",
                    "result": {
                        "method": "thread-follower-start-turn",
                        "result": {"result": {"turn": {"id": "turn-desktop-1"}}},
                    },
                }
            _write_frame(connection, response)


def _desktop_listener(tmp_path: Path) -> tuple[socket.socket, Path]:
    """创建满足生产所有权校验的测试Unix监听端点。

    Args:
        tmp_path: pytest提供且归属当前用户的隔离目录。

    Returns:
        已进入listen状态的套接字及其文件路径。

    Side Effects:
        创建权限为0700的IPC目录和一个本机Unix套接字文件。
    """

    # macOS限制Unix套接字路径长度；在系统临时根下创建短目录仍保持每个测试独立。
    ipc_directory = Path(
        tempfile.mkdtemp(prefix=f"ot-ipc-{tmp_path.name[-4:]}-", dir=tempfile.gettempdir())
    )
    ipc_directory.chmod(0o700)
    socket_path = ipc_directory / "ipc.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    return listener, socket_path


def _close_desktop_listener(listener: socket.socket, socket_path: Path, server: threading.Thread) -> None:
    """关闭测试IPC服务并清理短路径套接字目录。

    Args:
        listener: 测试创建的Unix监听套接字。
        socket_path: 监听套接字在文件系统中的路径。
        server: 处理本次短连接的测试线程。

    Side Effects:
        关闭监听器、等待服务线程退出并删除测试专属套接字与空目录。
    """

    listener.close()
    server.join(timeout=2)
    if socket_path.exists():
        socket_path.unlink()
    socket_path.parent.rmdir()


def test_codex_desktop_bridge_starts_turn_through_current_owner(tmp_path: Path) -> None:
    """桥接应发现桌面owner并只向该owner转发原线程turn。

    Args:
        tmp_path: pytest隔离的同用户Unix套接字目录。

    Returns:
        None；请求版本、请求ID、目标owner和最小turn载荷均正确时通过。
    """

    listener, socket_path = _desktop_listener(tmp_path)
    requests: list[dict[str, Any]] = []
    server = threading.Thread(
        target=_serve_desktop_owner,
        args=(listener, requests),
        name="test-codex-desktop-owner",
    )
    server.start()
    try:
        bridge = CodexDesktopBridge(
            CodexDesktopBridgeConfig(socket_paths=(socket_path,), timeout_seconds=2)
        )
        result = bridge.start_turn(
            "01a-client-handoff-test",
            "$knowledge-handoff 请继续当前任务。",
            "gpt-5.6-luna",
            "low",
        )
    finally:
        _close_desktop_listener(listener, socket_path, server)

    assert result.state == "started"
    assert result.turn_id == "turn-desktop-1"
    assert [request["version"] for request in requests] == [0, 1, 2]
    assert len({request["requestId"] for request in requests}) == 3
    assert requests[1]["params"] == {
        "hostId": "local",
        "conversationId": "01a-client-handoff-test",
    }
    follower_request = requests[2]
    assert follower_request["targetClientId"] == "desktop-owner"
    assert follower_request["params"]["conversationId"] == "01a-client-handoff-test"
    assert follower_request["params"]["turnStart"]["request"]["threadId"] == "01a-client-handoff-test"
    assert follower_request["params"]["turnStart"]["request"]["model"] == "gpt-5.6-luna"
    assert follower_request["params"]["turnStart"]["request"]["effort"] == "low"
    assert follower_request["params"]["turnStart"]["request"]["input"] == [
        {
            "type": "text",
            "text": "$knowledge-handoff 请继续当前任务。",
            "text_elements": [],
        }
    ]


def test_codex_desktop_bridge_returns_manual_required_for_version_mismatch(tmp_path: Path) -> None:
    """桌面follower版本不兼容时应提示原任务手动开始且不抢占writer。

    Args:
        tmp_path: pytest隔离的同用户Unix套接字目录。

    Returns:
        None；桥接返回manual_required且保留精确协议版本请求时通过。
    """

    listener, socket_path = _desktop_listener(tmp_path)
    requests: list[dict[str, Any]] = []
    server = threading.Thread(
        target=_serve_desktop_owner,
        args=(listener, requests, "request-version-mismatch"),
        name="test-codex-desktop-version-mismatch",
    )
    server.start()
    try:
        bridge = CodexDesktopBridge(
            CodexDesktopBridgeConfig(socket_paths=(socket_path,), timeout_seconds=2)
        )
        result = bridge.start_turn(
            "01a-client-handoff-test",
            "$knowledge-handoff 请继续当前任务。",
            "gpt-5.6-luna",
            "low",
        )
    finally:
        _close_desktop_listener(listener, socket_path, server)

    assert result.state == "manual_required"
    assert "协议版本" in result.safe_message
    assert len(requests) == 3


def test_codex_desktop_bridge_returns_manual_required_without_local_socket(tmp_path: Path) -> None:
    """桌面IPC不存在时应只返回手动开始提示而不创建任何替代连接。

    Args:
        tmp_path: pytest隔离且不含Unix套接字的目录。

    Returns:
        None；结果明确为manual_required时通过。
    """

    bridge = CodexDesktopBridge(
        CodexDesktopBridgeConfig(socket_paths=(tmp_path / "missing.sock",), timeout_seconds=1)
    )

    result = bridge.start_turn(
        "01a-client-handoff-test",
        "$knowledge-handoff 请继续当前任务。",
        "gpt-5.6-luna",
        "low",
    )

    assert result.state == "manual_required"
    assert "手动发送开始消息" in result.safe_message
