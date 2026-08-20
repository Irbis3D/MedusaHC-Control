from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class MoonrakerError(RuntimeError):
    pass


class MoonrakerClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._objects: set[str] | None = None
        self._objects_updated_at = 0.0

    def _request(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout if timeout is None else timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise MoonrakerError(f"Moonraker returned HTTP {exc.code}: {message}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise MoonrakerError(f"Cannot communicate with Moonraker: {exc}") from exc
        if isinstance(result, dict) and "error" in result:
            raise MoonrakerError(str(result["error"]))
        return result.get("result", result) if isinstance(result, dict) else result

    def list_objects(self, refresh: bool = False) -> set[str]:
        cache_expired = time.monotonic() - self._objects_updated_at > 10.0
        if self._objects is None or refresh or cache_expired:
            result = self._request("/printer/objects/list")
            self._objects = set(result.get("objects", []))
            self._objects_updated_at = time.monotonic()
        return set(self._objects)

    def query_status(self) -> dict[str, Any]:
        objects = self.list_objects()
        wanted = {
            "webhooks",
            "toolhead",
            "print_stats",
            "idle_timeout",
            "toolchanger",
            "pin_watch io",
            "mhc_dashboard",
            "medusahc",
            "save_variables",
            "gcode_macro TOOL_CFG",
            "gcode_macro GLOBAL_STATE",
            "gcode_macro TOOL_OFFSET",
        }
        for name in objects:
            if (
                name == "extruder"
                or re.fullmatch(r"extruder\d+", name)
                or re.fullmatch(r"gcode_macro T\d+", name)
                or re.fullmatch(r"gcode_macro TOOL_STATE_\d+", name)
            ):
                wanted.add(name)
        selected = sorted(wanted & objects)
        if not selected:
            raise MoonrakerError("Klipper is connected but no relevant printer objects were found")
        query = "&".join(quote(name, safe="") for name in selected)
        result = self._request(f"/printer/objects/query?{query}")
        return result.get("status", {})

    def list_webcams(self) -> list[dict[str, Any]]:
        result = self._request("/server/webcams/list")
        webcams = result.get("webcams", []) if isinstance(result, dict) else []
        return [item for item in webcams if isinstance(item, dict)]

    def send_gcode(self, script: str, timeout: float | None = None) -> None:
        self._request(
            "/printer/gcode/script",
            method="POST",
            payload={"script": script},
            timeout=timeout,
        )

    def emergency_stop(self) -> None:
        self._request("/printer/emergency_stop", method="POST", payload={})

    def restart_klipper(self) -> None:
        self._request("/printer/restart", method="POST", payload={})

    def restart_firmware(self) -> None:
        self._request("/printer/firmware_restart", method="POST", payload={})

    def reboot_device(self) -> None:
        self._request("/machine/reboot", method="POST", payload={})
