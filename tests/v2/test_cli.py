"""验证不依赖HTTP运行时的OpenTest V2 CLI错误和成功契约。"""

from __future__ import annotations

import json
from pathlib import Path

from opentest.cli import main


def test_cli_initializes_and_registers_system(tmp_path: Path, capsys: object) -> None:
    """CLI成功注册系统时应输出机器可读JSON并写入同一知识registry。"""

    source = tmp_path / "source"
    source.mkdir()
    knowledge_root = tmp_path / "knowledge"
    exit_code = main(
        [
            "--knowledge-root",
            str(knowledge_root),
            "register-system",
            "train-booking-core",
            "火车票预订",
            str(source),
        ]
    )
    # pytest运行时注入的capture对象负责隔离标准输出，不依赖其内部实现类型。
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["success"] is True
    assert payload["result"]["system_id"] == "train-booking-core"
    assert (knowledge_root / "registry" / "systems.yaml").exists()


def test_cli_maps_invalid_system_to_structured_validation_error(tmp_path: Path, capsys: object) -> None:
    """非法系统定义不得打印traceback或在校验失败前写入知识目录。"""

    source = tmp_path / "source"
    source.mkdir()
    knowledge_root = tmp_path / "knowledge"
    exit_code = main(
        [
            "--knowledge-root",
            str(knowledge_root),
            "register-system",
            "INVALID_SYSTEM",
            "火车票预订",
            str(source),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert exit_code == 2
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"
    assert not (knowledge_root / "registry" / "systems.yaml").exists()
