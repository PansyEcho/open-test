from __future__ import annotations

import argparse
import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .services import Platform


WEB_ROOT = Path(__file__).parent / "web"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class PlatformRequestHandler(BaseHTTPRequestHandler):
    platform: Platform

    server_version = "AITestPlatform/0.1"

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.path.startswith("/api/health"):
            return
        super().log_message(fmt, *args)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                result = self._handle_api(method, parsed.path, parse_qs(parsed.query))
                self._send_json(result)
            else:
                self._serve_static(parsed.path)
        except ApiError as exc:
            self._send_json({"success": False, "error": exc.message}, status=exc.status)
        except Exception as exc:  # pragma: no cover - keeps local server debuggable
            self._send_json(
                {
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=5),
                },
                status=500,
            )

    def _handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> Any:
        segments = [unquote(part) for part in path.strip("/").split("/")]
        body = self._read_json_body()
        platform = self.platform

        if method == "GET" and segments == ["api", "health"]:
            return {"success": True, "service": "ai-test-platform", "data_root": str(platform.data_root)}
        if method == "GET" and segments == ["api", "agents", "detect"]:
            return {"success": True, "agents": platform.detect_agents()}
        if method == "GET" and segments == ["api", "projects"]:
            return {"success": True, "projects": platform.list_projects()}
        if method == "POST" and segments == ["api", "projects"]:
            return {"success": True, "project": platform.create_project(body)}
        if len(segments) >= 3 and segments[:2] == ["api", "projects"]:
            project_id = segments[2]
            if method == "GET" and len(segments) == 3:
                return {"success": True, "project": platform.get_project(project_id)}
            if method == "POST" and segments[3:] == ["knowledge", "generate"]:
                return {"success": True, "draft": platform.generate_knowledge(project_id, body.get("message", ""))}
            if method == "POST" and segments[3:] == ["cli", "build-all"]:
                return {"success": True, "draft": platform.generate_cli(project_id, body)}
            if method == "POST" and segments[3:] == ["cases", "generate"]:
                return {"success": True, "draft": platform.generate_cases(project_id, body.get("scope", "main-flow"))}
            if method == "POST" and len(segments) == 6 and segments[3] == "drafts" and segments[5] == "confirm":
                return {"success": True, "version": platform.confirm_draft(project_id, segments[4])}
            if method == "POST" and segments[3:] == ["snapshots"]:
                return {"success": True, "snapshot": platform.create_snapshot(project_id)}
            if method == "POST" and segments[3:] == ["runs"]:
                return {"success": True, "run": platform.run_regression(project_id, body.get("snapshot_id"))}
            if method == "GET" and segments[3:] == ["runs"]:
                return {"success": True, "runs": platform.list_runs(project_id)}
            if method == "GET" and len(segments) == 5 and segments[3] == "runs":
                return {"success": True, "run": platform.get_run(project_id, segments[4])}

        raise ApiError(404, f"unknown route: {method} {path}")

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def _serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            target = WEB_ROOT / "index.html"
        else:
            clean = request_path.lstrip("/")
            target = (WEB_ROOT / clean).resolve()
            if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
                raise ApiError(403, "invalid static path")
        if not target.exists() or not target.is_file():
            raise ApiError(404, "static file not found")
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        payload = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._send_common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")


def create_server(host: str, port: int, data_root: str | None = None) -> ThreadingHTTPServer:
    handler = type("ConfiguredPlatformRequestHandler", (PlatformRequestHandler,), {})
    handler.platform = Platform(data_root=data_root)
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local AI test platform MVP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port, args.data_root)
    print(f"AI Test Platform listening on http://{args.host}:{args.port}")
    print(f"Data root: {server.RequestHandlerClass.platform.data_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
