"""在FastAPI依赖不可用时也能验证V2控制台静态安全契约。"""

from __future__ import annotations

from pathlib import Path


def test_console_static_client_uses_only_v2_routes_and_safe_rendering() -> None:
    """静态客户端应集中使用V2前缀，并通过textContent展示业务响应。"""

    web_root = Path(__file__).parents[2] / "opentest" / "web"
    html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "app.js").read_text(encoding="utf-8")

    assert "OpenTest V2 Console" in html
    assert 'const API_ROOT = "/api/v2"' in script
    assert "/api/projects" not in script
    assert "/resource-probes" in script
    assert "/oracle-operations" in script
    assert "/regression-suites/" in script
    assert 'value="suite:train-booking-core:core-order-lifecycle-v2"' in html
    assert "estimated_process_count" in script
    assert "non_test_order_count" in script
    assert ".innerHTML" not in script
    assert ".textContent" in script
    assert "EFFECT_ONLY：仅证明 MQ 消费后的业务效果" in html
    assert "Host、账号、密码、Token" in html
