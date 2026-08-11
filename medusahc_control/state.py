from __future__ import annotations

import time
from copy import deepcopy
import re
from typing import Any


GREEN = {"00C853", "00FF00"}
RED = {"D32F2F", "FF0000"}
BLUE = {"1976D2", "0000FF"}
def _macro(status: dict[str, Any], name: str) -> dict[str, Any]:
    value = status.get(f"gcode_macro {name}", {})
    return value if isinstance(value, dict) else {}


def normalize_status(status: dict[str, Any]) -> dict[str, Any]:
    global_state = _macro(status, "GLOBAL_STATE")
    tool_cfg = _macro(status, "TOOL_CFG")
    offsets = _macro(status, "TOOL_OFFSET")
    save_variables = status.get("save_variables", {}) or {}
    saved_values = save_variables.get("variables", {}) if isinstance(save_variables, dict) else {}
    if not isinstance(saved_values, dict):
        saved_values = {}
    pin_watch = status.get("mhc_dashboard", {}) or status.get("pin_watch io", {}) or {}
    tool_count = _tool_count(status, global_state, pin_watch)
    current_tool = int(pin_watch.get("current_tool", -2))
    raw_sensors = pin_watch.get("sensors", {}) or {}
    macro_values = {
        "TOOL_CFG": _numeric_variables(tool_cfg),
        "GLOBAL_STATE": _numeric_variables(global_state),
        "TOOL_OFFSET": _numeric_variables(offsets),
    }

    tools = []
    for index in range(tool_count):
        macro = _macro(status, f"T{index}")
        tool_state = _macro(status, f"TOOL_STATE_{index}")
        macro_values[f"TOOL_STATE_{index}"] = _numeric_variables(tool_state)
        heater_name = "extruder" if index == 0 else f"extruder{index}"
        heater = status.get(heater_name, {}) or {}
        color = str(macro.get("color", "")).replace("#", "").upper()
        raw_value = raw_sensors.get(f"t{index}")
        if index == current_tool:
            sensor_state = "active"
        elif raw_value is not None:
            sensor_state = "parked" if int(raw_value) == 1 else "released"
        elif color in GREEN:
            sensor_state = "parked"
        elif color in RED:
            sensor_state = "released"
        elif color in BLUE:
            sensor_state = "active"
        else:
            sensor_state = "unknown"
        tools.append(
            {
                "number": index,
                "name": f"T{index}",
                "active": index == current_tool or bool(macro.get("active", 0)),
                "sensor": sensor_state,
                "temperature": round(float(heater.get("temperature", 0.0)), 1),
                "target": round(float(heater.get("target", 0.0)), 1),
                "power": round(float(heater.get("power", 0.0)) * 100, 1),
                "dock_x": float(tool_cfg.get(f"x_t{index}", 0.0)),
                "offsets": {
                    "x": float(offsets.get(f"t{index}_off_x", 0.0)),
                    "y": float(offsets.get(f"t{index}_off_y", 0.0)),
                    "z": float(offsets.get(f"t{index}_off_z", 0.0)),
                },
                "process": _numeric_variables(tool_state),
            }
        )

    webhooks = status.get("webhooks", {}) or {}
    print_stats = status.get("print_stats", {}) or {}
    toolhead = status.get("toolhead", {}) or {}
    raw_position = toolhead.get("position", [0.0, 0.0, 0.0, 0.0])
    if not isinstance(raw_position, (list, tuple)) or len(raw_position) < 3:
        raw_position = [0.0, 0.0, 0.0, 0.0]
    klipper_state = str(webhooks.get("state", "unknown"))
    print_state = str(print_stats.get("state", "standby"))
    homed_axes = str(toolhead.get("homed_axes", ""))
    ready = klipper_state == "ready"
    printing = print_state in {"printing", "paused"}
    sensor_error = current_tool == -2
    can_move = ready and not printing and not sensor_error
    settings = {}
    settings.update({key: value for key, value in tool_cfg.items() if not key.startswith("_")})
    settings["eddy_z"] = float(global_state.get("eddy_z", 0.0))

    return {
        "connected": True,
        "simulated": False,
        "control_enabled": True,
        "timestamp": time.time(),
        "klipper_state": klipper_state,
        "print_state": print_state,
        "filename": print_stats.get("filename", ""),
        "homed_axes": homed_axes,
        "position": {
            "x": round(float(raw_position[0]), 2),
            "y": round(float(raw_position[1]), 2),
            "z": round(float(raw_position[2]), 2),
        },
        "layout": "front" if int(tool_cfg.get("tools_direction", 1)) == 1 else "rear",
        "tool_count": tool_count,
        "current_tool": current_tool,
        "target_tool": int(global_state.get("target_tool", -1)),
        "sensor_error": sensor_error,
        "feeder_open": bool(global_state.get("feeder_open", 0)),
        "tools": tools,
        "sensors": {str(key): int(value) for key, value in raw_sensors.items()},
        "settings": settings,
        "macro_values": macro_values,
        "saved_variables": _numeric_variables(saved_values),
        "capabilities": {
            "can_home": ready and not printing,
            "can_jog": ready and not printing,
            "can_heat": ready,
            "can_select": can_move,
            "can_drop": can_move and current_tool >= 0,
            "can_clean": can_move and current_tool >= 0,
            "can_feeder": ready and not printing,
            "can_calibrate": can_move,
            "can_edit": ready and not printing,
            "can_system": True,
        },
        "message": _state_message(current_tool, sensor_error),
    }


def _tool_count(
    status: dict[str, Any], global_state: dict[str, Any], pin_watch: dict[str, Any]
) -> int:
    """Read the configured count first, then fall back to discovered objects."""
    for value in (global_state.get("max_tool"), pin_watch.get("tool_count")):
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            return count

    indices: list[int] = []
    for name in (pin_watch.get("sensors", {}) or {}):
        match = re.fullmatch(r"t(\d+)", str(name))
        if match:
            indices.append(int(match.group(1)))
    for name in status:
        match = re.fullmatch(r"gcode_macro T(\d+)", str(name))
        if match:
            indices.append(int(match.group(1)))
        elif name == "extruder":
            indices.append(0)
        else:
            match = re.fullmatch(r"extruder(\d+)", str(name))
            if match:
                indices.append(int(match.group(1)))
    return max(indices) + 1 if indices else 1


def disconnected_state(message: str) -> dict[str, Any]:
    return {
        "connected": False,
        "simulated": False,
        "control_enabled": False,
        "timestamp": time.time(),
        "klipper_state": "disconnected",
        "print_state": "unknown",
        "filename": "",
        "homed_axes": "",
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "layout": "front",
        "tool_count": 0,
        "current_tool": -2,
        "target_tool": -1,
        "sensor_error": True,
        "feeder_open": False,
        "tools": [],
        "sensors": {},
        "settings": {},
        "macro_values": {},
        "saved_variables": {},
        "capabilities": {key: False for key in ("can_home", "can_jog", "can_heat", "can_select", "can_drop", "can_clean", "can_feeder", "can_calibrate", "can_edit", "can_system")},
        "message": message,
    }


def _state_message(current_tool: int, sensor_error: bool) -> str:
    if sensor_error:
        return "Sensor combination is ambiguous"
    if current_tool == -1:
        return "Toolhead is empty"
    return f"T{current_tool} is mounted"


def _numeric_variables(values: dict[str, Any]) -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for name, value in values.items():
        if str(name).startswith("_") or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result[str(name)] = value
    return result


class Simulator:
    def __init__(self, tool_count: int = 6):
        self._state = self._initial_state(tool_count)

    @staticmethod
    def _initial_state(tool_count: int) -> dict[str, Any]:
        raw: dict[str, Any] = {
            "webhooks": {"state": "ready"},
            "print_stats": {"state": "standby", "filename": ""},
            "toolhead": {"homed_axes": "xyz", "position": [150.0, 150.0, 10.0, 0.0]},
            "pin_watch io": {"current_tool": -1, "sensors": {"e": 0, **{f"t{i}": 1 for i in range(tool_count)}}},
            "gcode_macro GLOBAL_STATE": {
                "max_tool": tool_count, "target_tool": -1, "feeder_open": 0,
                "eddy_z": -0.09, "fast_feedrate": 30000,
                "slow_feedrate": 2400, "clean_feedrate": 3000,
            },
            "gcode_macro TOOL_CFG": {
                "tools_direction": -1,
                "y_safe": 300.0,
                "y_latch": 344.6,
                "x_shift": 9.0,
                "y_prime": 332.0,
                "y_brush": 332.0,
                "x_prime_shift": 12.0,
                "fast_accel": 10000,
                "fast_speed": 500,
                "slow_speed": 40,
                "clean_speed": 50,
                "e_open": -5.0,
                "e_close": 3.0,
                "e_cur_high_mult": 1.7,
                **{f"x_t{i}": 17 + i * 57 for i in range(tool_count)},
            },
            "gcode_macro TOOL_OFFSET": {},
            "save_variables": {"variables": {}},
        }
        for index in range(tool_count):
            raw["extruder" if index == 0 else f"extruder{index}"] = {"temperature": 24.0 + index * 0.3, "target": 0.0, "power": 0.0}
            raw[f"gcode_macro T{index}"] = {"active": 0, "color": "00C853"}
            raw[f"gcode_macro TOOL_STATE_{index}"] = {
                "prime_amount": 13, "prime_speed": 30, "prime_retract": 1,
                "prime_retract_speed": 30, "clean_move": 1, "x_clean_move": 8,
                "y_clean_move": 5, "clean_move_speed": 250,
                "ptfe_clean_slow_speed": 5, "clean_retract": 1,
                "clean_retract_speed": 30, "first_prime_flag": 1,
                "first_prime_amount": 20, "first_prime_speed": 20,
            }
            raw["gcode_macro TOOL_OFFSET"].update({
                f"t{index}_off_x": 0.0,
                f"t{index}_off_y": 0.0,
                f"t{index}_off_z": 0.0,
            })
            raw["save_variables"]["variables"].update({
                f"t{index}_gcode_x_offset": 0.0,
                f"t{index}_gcode_y_offset": 0.0,
                f"t{index}_gcode_z_offset": 0.0,
            })
        return raw

    def snapshot(self) -> dict[str, Any]:
        self._tick_temperatures()
        result = normalize_status(deepcopy(self._state))
        result["simulated"] = True
        result["control_enabled"] = True
        return result

    def _tick_temperatures(self) -> None:
        for name, heater in self._state.items():
            if not name.startswith("extruder") or not isinstance(heater, dict):
                continue
            current = float(heater.get("temperature", 24.0))
            target = float(heater.get("target", 0.0))
            ambient_target = target if target > 0 else 24.0
            delta = ambient_target - current
            heater["temperature"] = current + max(-2.5, min(3.5, delta * 0.08))
            heater["power"] = 0.75 if delta > 2 else 0.0

    def execute(self, action: str, payload: dict[str, Any]) -> None:
        pin_watch = self._state["pin_watch io"]
        global_state = self._state["gcode_macro GLOBAL_STATE"]
        current = int(pin_watch["current_tool"])
        if action == "select_tool":
            tool = int(payload["tool"])
            if current >= 0:
                pin_watch["sensors"][f"t{current}"] = 1
                self._state[f"gcode_macro T{current}"]["active"] = 0
                self._state[f"gcode_macro T{current}"]["color"] = "00C853"
            pin_watch["sensors"][f"t{tool}"] = 0
            pin_watch["sensors"]["e"] = 1
            pin_watch["current_tool"] = tool
            global_state["target_tool"] = tool
            self._state[f"gcode_macro T{tool}"]["active"] = 1
            self._state[f"gcode_macro T{tool}"]["color"] = "1976D2"
        elif action == "drop_tool" and current >= 0:
            pin_watch["sensors"][f"t{current}"] = 1
            pin_watch["sensors"]["e"] = 0
            pin_watch["current_tool"] = -1
            global_state["target_tool"] = -1
            self._state[f"gcode_macro T{current}"]["active"] = 0
            self._state[f"gcode_macro T{current}"]["color"] = "00C853"
        elif action == "feeder_open":
            global_state["feeder_open"] = 1
        elif action == "feeder_close":
            global_state["feeder_open"] = 0
        elif action == "set_temperature":
            tool = int(payload["tool"])
            name = "extruder" if tool == 0 else f"extruder{tool}"
            self._state[name]["target"] = float(payload["temperature"])
        elif action == "home":
            self._state["toolhead"]["homed_axes"] = "xyz"
        elif action == "home_axis":
            axis = str(payload["axis"]).lower()
            homed = set(self._state["toolhead"].get("homed_axes", ""))
            homed.add(axis)
            self._state["toolhead"]["homed_axes"] = "".join(sorted(homed))
        elif action == "jog":
            axis_index = {"X": 0, "Y": 1, "Z": 2}[str(payload["axis"]).upper()]
            self._state["toolhead"]["position"][axis_index] += float(payload["distance"])
        elif action in {"clean", "test_tools", "calibrate_xyz", "calibrate_z", "calibrate_bed", "calibrate_z_tilt", "emergency_stop", "restart_klipper", "restart_firmware", "reboot_device"}:
            if action == "emergency_stop":
                self._state["webhooks"]["state"] = "shutdown"

    def set_setting(
        self, definition: dict[str, Any], value: float | int, *, permanent: bool = False
    ) -> None:
        macro = f"gcode_macro {definition['macro']}"
        self._state.setdefault(macro, {})[definition["variable"]] = value
        for target in definition.get("active_runtime_targets", []):
            target_macro = f"gcode_macro {target['macro']}"
            target_value = float(value) * float(target.get("multiplier", 1))
            self._state.setdefault(target_macro, {})[target["variable"]] = target_value
        if permanent and definition.get("kind") == "tool_offset" and definition.get("saved_variable"):
            self._state["save_variables"]["variables"][definition["saved_variable"]] = value
