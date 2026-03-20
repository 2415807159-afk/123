from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def resolve_safe_path(rel_path: str) -> Path:
    normalized = str(rel_path or "").replace("\\", "/").lstrip("/")
    candidate = (ROOT / normalized).resolve()
    root_resolved = ROOT.resolve()
    if root_resolved not in candidate.parents and candidate != root_resolved:
        raise ValueError(f"Path escapes workspace: {rel_path}")
    return candidate


class DPRLocalHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        sys.stdout.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "root": str(ROOT),
                    "pid": os.getpid(),
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/write-files":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        files = payload.get("files")
        if not isinstance(files, list) or not files:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "files must be a non-empty array"})
            return

        written = []
        try:
            for item in files:
                if not isinstance(item, dict):
                    raise ValueError("Each file entry must be an object")
                rel_path = str(item.get("path") or "").strip()
                content = item.get("content")
                if not rel_path:
                    raise ValueError("File path is required")
                if not isinstance(content, str):
                    raise ValueError(f"Content for {rel_path} must be a string")
                target = resolve_safe_path(rel_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written.append(rel_path.replace("\\", "/"))
        except Exception as exc:  # noqa: BLE001
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc), "written": written})
            return

        self._send_json(HTTPStatus.OK, {"ok": True, "written": written, "count": len(written)})


def main() -> None:
    port = 8765
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            port = 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), DPRLocalHandler)
    print(f"Daily Paper Reader local server running at http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
