from __future__ import annotations

import logging
import queue
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config import AppConfig
from .config_store import ConfigStore
from .database import StatsDatabase
from .moonraker import MoonrakerClient, MoonrakerError
from .settings import schema_for, validate_setting
from .state import Simulator, disconnected_state, normalize_status


LOG = logging.getLogger(__name__)


class SafetyError(RuntimeError):
    pass


ACTION_CAPABILITY = {
    "home": "can_home",
    "home_axis": "can_home",
    "jog": "can_jog",
    "select_tool": "can_select",
    "drop_tool": "can_drop",
    "clean": "can_clean",
    "test_tools": "can_select",
    "feeder_open": "can_feeder",
    "feeder_close": "can_feeder",
    "calibrate_xyz": "can_calibrate",
    "calibrate_z": "can_calibrate",
    "calibrate_bed": "can_calibrate",
    "calibrate_z_tilt": "can_calibrate",
    "set_temperature": "can_heat",
    "restart_klipper": "can_system",
    "restart_firmware": "can_system",
    "reboot_device": "can_system",
}

QUEUED_ACTIONS = {
    "home", "home_axis", "select_tool", "drop_tool", "clean", "test_tools",
    "feeder_open", "feeder_close", "calibrate_xyz", "calibrate_z",
    "calibrate_bed", "calibrate_z_tilt",
}


class ControlService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.database = StatsDatabase(config.database_path)
        self._simulator = Simulator() if config.simulate else None
        self._moonraker = None if config.simulate else MoonrakerClient(
            config.moonraker_url, config.moonraker_api_key
        )
        self._state = self._simulator.snapshot() if self._simulator else disconnected_state("Connecting to Moonraker")
        self._state_lock = threading.RLock()
        self._control_active = bool(config.simulate or config.allow_commands)
        self._config_store = None
        if not config.simulate and config.medusahc_variables_path:
            self._config_store = ConfigStore(
                config.medusahc_variables_path,
                Path(config.database_path).parent / "backups",
            )
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._command_queue: queue.Queue[tuple[str, str, int | None]] = queue.Queue(maxsize=32)
        self._command_thread: threading.Thread | None = None

    def start(self) -> None:
        self._poll_thread = threading.Thread(target=self._poll_loop, name="moonraker-poll", daemon=True)
        self._poll_thread.start()
        if self._moonraker is not None:
            self._command_thread = threading.Thread(
                target=self._command_loop, name="moonraker-command", daemon=True
            )
            self._command_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3.0)
        if self._command_thread is not None:
            self._command_thread.join(timeout=3.0)
        self.database.close()

    def _command_loop(self) -> None:
        assert self._moonraker is not None
        while not self._stop.is_set():
            try:
                action, script, tool = self._command_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._moonraker.send_gcode(script, timeout=3600.0)
                self.database.record("command_completed", tool=tool, details={"action": action})
            except MoonrakerError as exc:
                LOG.error("Queued command %s failed: %s", action, exc)
                self.database.record(
                    "command_failed", tool=tool, success=False,
                    details={"action": action, "error": str(exc)},
                )
            finally:
                self._command_queue.task_done()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._simulator is not None:
                    state = self._simulator.snapshot()
                else:
                    assert self._moonraker is not None
                    state = normalize_status(self._moonraker.query_status())
                with self._state_lock:
                    self._state = state
                self.database.observe(state)
            except MoonrakerError as exc:
                with self._state_lock:
                    self._state = disconnected_state(str(exc))
            except Exception as exc:
                LOG.exception("Unexpected polling failure")
                with self._state_lock:
                    self._state = disconnected_state(f"Internal service error: {exc}")
            self._stop.wait(max(0.2, self.config.poll_interval))

    def state(self) -> dict[str, Any]:
        with self._state_lock:
            state = deepcopy(self._state)
            active = bool(self._control_active)
        state["control_available"] = bool(self._simulator is not None or self.config.allow_commands)
        state["control_enabled"] = active
        if not active:
            state["capabilities"] = {
                key: False for key in state.get("capabilities", {})
            }
        return state

    def set_control_mode(self, enabled: bool) -> dict[str, Any]:
        if enabled and self._simulator is None and not self.config.allow_commands:
            raise SafetyError("Live control is disabled in medusahc-control.json")
        with self._state_lock:
            self._control_active = bool(enabled)
        self.database.record(
            "control_mode",
            details={"enabled": bool(enabled), "simulated": self._simulator is not None},
        )
        return {"ok": True, "control_enabled": bool(enabled)}

    def settings_payload(self) -> dict[str, Any]:
        state = self.state()
        schema, discovery_warning = self._settings_schema(state)
        macro_values = state.get("macro_values", {})
        saved_variables = state.get("saved_variables", {})
        values: dict[str, float | int] = {}
        for definition in schema:
            if not definition.get("available", True):
                continue
            macro = str(definition["macro"])
            variable = str(definition["variable"])
            current = macro_values.get(macro, {})
            if variable in current:
                values[str(definition["key"])] = current[variable]
            if definition.get("kind") == "tool_offset":
                saved_variable = str(definition.get("saved_variable", ""))
                if saved_variable in saved_variables:
                    definition["configured_value"] = saved_variables[saved_variable]
        layout = self.database.settings_layout()
        self._apply_settings_layout(schema, layout)
        return {
            "schema": schema,
            "values": values,
            "history": self.database.setting_history([item["key"] for item in schema]),
            "file_write_available": self._simulator is not None or bool(self._config_store and self._config_store.available),
            "discovery_warning": discovery_warning,
            "layout": layout,
        }

    @staticmethod
    def _apply_settings_layout(schema: list[dict[str, Any]], layout: dict[str, Any]) -> None:
        if not layout.get("customized"):
            for position, definition in enumerate(schema):
                definition["visible"] = bool(definition.get("default_visible", True))
                definition["layout_order"] = position
            return
        entries = {
            str(item["layout_key"]): item
            for item in layout.get("entries", [])
            if isinstance(item, dict) and item.get("layout_key")
        }
        for definition in schema:
            entry = entries.get(str(definition["layout_key"]))
            definition["visible"] = entry is not None
            definition["layout_order"] = int(entry.get("position", 0)) if entry else 1_000_000
            if entry is not None:
                definition["description"] = str(entry.get("description", ""))

    def save_settings_layout(self, entries: Any) -> dict[str, Any]:
        if not isinstance(entries, list):
            raise ValueError("Layout entries must be a list")
        if len(entries) > 512:
            raise ValueError("Layout contains too many variables")
        schema, _warning = self._settings_schema(self.state())
        allowed = {str(item["layout_key"]) for item in schema}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for position, item in enumerate(entries):
            if not isinstance(item, dict):
                raise ValueError("Each layout entry must be an object")
            layout_key = str(item.get("layout_key", ""))
            if layout_key not in allowed:
                raise ValueError(f"Unknown settings variable: {layout_key}")
            if layout_key in seen:
                raise ValueError(f"Duplicate settings variable: {layout_key}")
            description = str(item.get("description", "")).strip()
            if len(description) > 1000:
                raise ValueError("Variable descriptions cannot exceed 1000 characters")
            seen.add(layout_key)
            normalized.append({
                "layout_key": layout_key,
                "position": position,
                "description": description,
            })
        layout = self.database.save_settings_layout(normalized)
        self.database.record("settings_layout_changed", details={"visible_variables": len(normalized)})
        return {"ok": True, "layout": layout}

    def reset_settings_layout(self) -> dict[str, Any]:
        layout = self.database.reset_settings_layout()
        self.database.record("settings_layout_reset")
        return {"ok": True, "layout": layout}

    def _settings_schema(self, state: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        discovery_warning = ""
        if self._simulator is not None:
            discovered = None
        elif self._config_store is None:
            discovered = {}
            discovery_warning = "MedusaHC variables file is not configured for the dashboard."
        else:
            try:
                discovered = self._config_store.inspect_variables()
            except (OSError, UnicodeError, ValueError) as exc:
                discovered = {}
                discovery_warning = str(exc)

        schema = schema_for(
            int(state.get("tool_count", 1) or 1),
            discovered,
            discovery_warning,
        )
        macro_values = state.get("macro_values", {})
        for definition in schema:
            if not definition.get("available", True):
                continue
            macro = str(definition["macro"])
            variable = str(definition["variable"])
            if variable not in macro_values.get(macro, {}):
                definition["available"] = False
                definition["availability_reason"] = (
                    f"variable_{variable} is not available in the running "
                    f"[gcode_macro {macro}] configuration"
                )
        return schema, discovery_warning

    def camera_payload(self) -> dict[str, Any]:
        if self._simulator is not None:
            return {"available": False, "name": "Simulation", "stream_url": "", "aspect_ratio": "4:3"}
        assert self._moonraker is not None
        webcams = self._moonraker.list_webcams()
        camera = next((item for item in webcams if item.get("enabled", True)), None)
        if not camera:
            return {"available": False, "name": "No enabled camera", "stream_url": "", "aspect_ratio": "4:3"}
        return {
            "available": True,
            "name": str(camera.get("name", "Camera")),
            "stream_url": str(camera.get("stream_url", "")),
            "snapshot_url": str(camera.get("snapshot_url", "")),
            "aspect_ratio": str(camera.get("aspect_ratio", "4:3")),
            "flip_horizontal": bool(camera.get("flip_horizontal", False)),
            "flip_vertical": bool(camera.get("flip_vertical", False)),
            "rotation": int(camera.get("rotation", 0) or 0),
            "target_fps": int(camera.get("target_fps", 5) or 5),
        }

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.state()
        if not state.get("control_enabled") and not (
            action == "emergency_stop" and state.get("control_available")
        ):
            raise SafetyError("Control mode is passive. Enable control before sending commands")
        if action != "emergency_stop":
            capability = ACTION_CAPABILITY.get(action)
            if capability is None:
                raise ValueError(f"Unsupported action: {action}")
            if not bool(state.get("capabilities", {}).get(capability, False)):
                raise SafetyError(self._safety_reason(action, state))

        tool: int | None = None
        if action in {"select_tool", "set_temperature"}:
            tool = int(payload.get("tool", -1))
            if tool < 0 or tool >= int(state.get("tool_count", 0)):
                raise ValueError("Tool number is outside the configured range")
        if action in {"home_axis", "jog"}:
            axis = str(payload.get("axis", "")).upper()
            if axis not in {"X", "Y", "Z"}:
                raise ValueError("Axis must be X, Y or Z")
            payload["axis"] = axis
        if action == "jog":
            distance = float(payload.get("distance", 0))
            speed = float(payload.get("speed", 0))
            distance_limit = 25.0 if payload["axis"] == "Z" else 100.0
            if distance == 0 or abs(distance) > distance_limit:
                raise ValueError(f"Jog distance must be non-zero and no more than {distance_limit:g} mm")
            if speed < 0.1 or speed > 300:
                raise ValueError("Jog speed must be between 0.1 and 300 mm/s")
            payload["distance"] = distance
            payload["speed"] = speed
        if action == "set_temperature":
            temperature = float(payload.get("temperature", 0))
            if temperature < 0 or temperature > self.config.max_temperature:
                raise ValueError(f"Temperature must be between 0 and {self.config.max_temperature:g} °C")

        queued = False
        if self._simulator is not None:
            self._simulator.execute(action, payload)
        else:
            assert self._moonraker is not None
            if action == "emergency_stop":
                self._announce(action, payload)
                self._moonraker.emergency_stop()
            elif action == "restart_klipper":
                self._announce(action, payload)
                self._moonraker.restart_klipper()
            elif action == "restart_firmware":
                self._announce(action, payload)
                self._moonraker.restart_firmware()
            elif action == "reboot_device":
                self._announce(action, payload)
                self._moonraker.reboot_device()
            elif action in QUEUED_ACTIONS:
                try:
                    self._command_queue.put_nowait((action, self._console_gcode(action, payload), tool))
                except queue.Full as exc:
                    raise SafetyError("The printer command queue is full") from exc
                queued = True
            else:
                self._moonraker.send_gcode(self._console_gcode(action, payload))
        self.database.record(
            "command",
            tool=tool,
            details={"action": action, "simulated": self._simulator is not None, "queued": queued},
        )
        return {"ok": True, "action": action, "queued": queued}

    def set_setting(self, key: str, value: Any, mode: str = "runtime") -> dict[str, Any]:
        state = self.state()
        if not state.get("control_enabled"):
            raise SafetyError("Control mode is passive. Enable control before changing settings")
        if mode not in {"runtime", "permanent"}:
            raise ValueError("Setting mode must be runtime or permanent")
        if not state.get("connected") or state.get("klipper_state") != "ready":
            raise SafetyError("Klipper must be ready before changing settings")
        if mode != "runtime" and state.get("print_state") in {"printing", "paused"}:
            raise SafetyError("Configuration files cannot be changed while a print is active or paused")
        schema, _discovery_warning = self._settings_schema(state)
        definition, numeric = validate_setting(key, value, schema)
        print_active = state.get("print_state") in {"printing", "paused"}
        if definition.get("page") == "setup" and print_active:
            raise SafetyError("Printer setup parameters can only be changed while the printer is idle")
        if self._simulator is not None:
            self._simulator.set_setting(definition, numeric, permanent=mode == "permanent")
            with self._state_lock:
                self._state = self._simulator.snapshot()
        else:
            assert self._moonraker is not None
            self._send_setting(definition, numeric)
            self._apply_active_offset(definition, state)
            if mode == "permanent":
                if not self._config_store or not self._config_store.available:
                    raise SafetyError("Printer configuration files are not available to the dashboard")
                if definition.get("kind") == "tool_offset":
                    self._moonraker.send_gcode(
                        f"SAVE_VARIABLE VARIABLE={definition['saved_variable']} VALUE={numeric}"
                    )
                else:
                    self._config_store.save_permanent(definition, numeric)
        self.database.record_setting(key, numeric, mode)
        self.database.record(
            "setting_changed",
            details={"key": key, "value": numeric, "mode": mode},
        )
        return {"ok": True, "key": key, "value": numeric, "mode": mode}

    def _send_setting(self, definition: dict[str, Any], numeric: float | int) -> None:
        assert self._moonraker is not None
        self._moonraker.send_gcode(
            f'RESPOND TYPE=command MSG="MedusaHC Control: apply {definition["label"]} = {numeric}"\n'
            f"SET_GCODE_VARIABLE MACRO={definition['macro']} "
            f"VARIABLE={definition['variable']} VALUE={numeric}"
        )

    def _announce(self, action: str, payload: dict[str, Any]) -> None:
        assert self._moonraker is not None
        try:
            self._moonraker.send_gcode(
                f'RESPOND TYPE=command MSG="MedusaHC Control: {self._console_message(action, payload)}"'
            )
        except MoonrakerError as exc:
            # Restarts must remain available when Klipper itself is not ready.
            LOG.info("Could not write system action to Klipper console: %s", exc)

    @classmethod
    def _console_gcode(cls, action: str, payload: dict[str, Any]) -> str:
        return (
            f'RESPOND TYPE=command MSG="MedusaHC Control: {cls._console_message(action, payload)}"\n'
            f"{cls._gcode(action, payload)}"
        )

    @staticmethod
    def _console_message(action: str, payload: dict[str, Any]) -> str:
        messages = {
            "home": "home all axes",
            "drop_tool": "park current tool",
            "clean": "run cleaning cycle",
            "test_tools": "run tool test sequence",
            "feeder_open": "open feeder",
            "feeder_close": "close feeder",
            "calibrate_xyz": "start XYZ tool calibration",
            "calibrate_z": "start Z tool calibration",
            "calibrate_bed": "start bed calibration",
            "calibrate_z_tilt": "start Z tilt adjustment",
            "emergency_stop": "EMERGENCY STOP",
            "restart_klipper": "restart Klipper",
            "restart_firmware": "restart MCU firmware",
            "reboot_device": "reboot complete device",
        }
        if action == "home_axis":
            return f"home {payload['axis']} axis"
        if action == "jog":
            return f"jog {payload['axis']} {float(payload['distance']):g} mm"
        if action == "select_tool":
            return f"select T{int(payload['tool'])}"
        if action == "set_temperature":
            return f"set T{int(payload['tool'])} target to {float(payload['temperature']):g} C"
        return messages.get(action, action.replace("_", " "))

    def _apply_active_offset(self, definition: dict[str, Any], state: dict[str, Any]) -> None:
        if definition.get("kind") != "tool_offset":
            return
        tool = int(definition["tool"])
        if int(state.get("current_tool", -1)) == tool:
            assert self._moonraker is not None
            self._moonraker.send_gcode(f"TOOL_OFFSET_T T={tool} MOVE=0")

    @staticmethod
    def _safety_reason(action: str, state: dict[str, Any]) -> str:
        if not state.get("connected"):
            return "Moonraker is not connected"
        if state.get("print_state") in {"printing", "paused"}:
            return "Manual MedusaHC movement is blocked while a print is active or paused"
        if state.get("sensor_error"):
            return "Tool sensors report an ambiguous state"
        return "The action is blocked by the current printer state"

    @staticmethod
    def _gcode(action: str, payload: dict[str, Any]) -> str:
        if action == "home":
            return "G28"
        if action == "home_axis":
            return f"G28 {payload['axis']}"
        if action == "jog":
            axis = payload["axis"]
            distance = float(payload["distance"])
            feedrate = float(payload["speed"]) * 60.0
            return (
                "SAVE_GCODE_STATE NAME=MHC_CONTROL_JOG\n"
                "G91\n"
                f"G1 {axis}{distance:g} F{feedrate:g}\n"
                "RESTORE_GCODE_STATE NAME=MHC_CONTROL_JOG"
            )
        if action == "select_tool":
            return f"T{int(payload['tool'])}"
        if action == "drop_tool":
            return "DROP_TOOL"
        if action == "clean":
            return "CLEAN"
        if action == "test_tools":
            return "TEST_TOOLS"
        if action == "feeder_open":
            return "OPEN"
        if action == "feeder_close":
            return "CLOSE"
        if action == "calibrate_xyz":
            return "CALIBRATE_AND_SAVE_OFFSETS"
        if action == "calibrate_z":
            return "TOOL_Z_CALIBRATION"
        if action == "calibrate_bed":
            return "BED_CALIBRATION"
        if action == "calibrate_z_tilt":
            return "Z_TILT_ADJUST"
        if action == "set_temperature":
            tool = int(payload["tool"])
            heater = "extruder" if tool == 0 else f"extruder{tool}"
            return f"SET_HEATER_TEMPERATURE HEATER={heater} TARGET={float(payload['temperature']):g}"
        raise ValueError(f"Unsupported action: {action}")
