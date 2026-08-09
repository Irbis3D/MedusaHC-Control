from __future__ import annotations

import json
import logging
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .moonraker import MoonrakerError
from .service import ControlService, SafetyError


LOG = logging.getLogger(__name__)
WEB_ROOT = (Path(__file__).parent / "web").resolve()


class MedusaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: ControlService, config: AppConfig):
        super().__init__(address, RequestHandler)
        self.service = service
        self.config = config


class RequestHandler(BaseHTTPRequestHandler):
    server: MedusaHTTPServer

    def log_message(self, format_string: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), format_string % args)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            state = self.server.service.state()
            self._json({"ok": True, "connected": state.get("connected"), "simulated": state.get("simulated")})
            return
        if path == "/api/status":
            self._json(self.server.service.state())
            return
        if path == "/api/settings":
            self._json(self.server.service.settings_payload())
            return
        if path == "/api/camera":
            self._json(self.server.service.camera_payload())
            return
        if path == "/api/stats":
            self._json(self.server.service.database.summary())
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            self._require_token()
            payload = self._read_json()
            if path == "/api/control-mode":
                if not isinstance(payload.get("enabled"), bool):
                    raise ValueError("enabled must be true or false")
                self._json(self.server.service.set_control_mode(payload["enabled"]))
                return
            if path == "/api/command":
                action = str(payload.pop("action", ""))
                self._json(self.server.service.execute(action, payload))
                return
            if path == "/api/settings":
                self._json(
                    self.server.service.set_setting(
                        str(payload.get("key", "")), payload.get("value"), str(payload.get("mode", "runtime"))
                    )
                )
                return
            if path == "/api/stats/reset":
                self._json(self.server.service.database.reset_toolchange_stats())
                return
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, SafetyError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except MoonrakerError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        except PermissionError as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            LOG.exception("Request failed")
            self._json({"error": f"Internal service error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _require_token(self) -> None:
        expected = self.server.config.control_token
        if expected and self.headers.get("X-Medusa-Token", "") != expected:
            raise PermissionError("A valid MedusaHC control token is required")

    def _read_json(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if size < 0 or size > 65536:
            raise ValueError("Request body is too large")
        if not size:
            return {}
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        file_path = (WEB_ROOT / relative).resolve()
        try:
            file_path.relative_to(WEB_ROOT)
        except ValueError:
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if not file_path.is_file():
            if "." not in Path(relative).name:
                file_path = WEB_ROOT / "index.html"
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
        body = file_path.read_bytes()
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type + ("; charset=utf-8" if media_type.startswith("text/") or media_type == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def serve(config: AppConfig) -> None:
    service = ControlService(config)
    server = MedusaHTTPServer((config.bind, config.port), service, config)
    service.start()
    LOG.info("MedusaHC Control is available at http://%s:%d", config.bind, config.port)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        service.stop()
