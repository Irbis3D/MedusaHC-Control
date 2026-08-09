from __future__ import annotations

from typing import Any


BASE_SETTINGS: tuple[dict[str, Any], ...] = (
    {"key": "tools_direction", "macro": "TOOL_CFG", "variable": "tools_direction", "label": "Dock orientation", "group": "Layout", "type": "choice", "choices": [{"value": 1, "label": "Front"}, {"value": -1, "label": "Rear"}]},
    {"key": "y_safe", "macro": "TOOL_CFG", "variable": "y_safe", "label": "Safe Y", "group": "Layout", "unit": "mm", "min": -150, "max": 500, "step": 0.1},
    {"key": "y_latch", "macro": "TOOL_CFG", "variable": "y_latch", "label": "Latch Y", "group": "Layout", "unit": "mm", "min": -150, "max": 500, "step": 0.1},
    {"key": "x_shift", "macro": "TOOL_CFG", "variable": "x_shift", "label": "Latch movement", "group": "Layout", "unit": "mm", "min": 0, "max": 50, "step": 0.1},
    {"key": "y_prime", "macro": "TOOL_CFG", "variable": "y_prime", "label": "Prime Y", "group": "Cleaning and priming", "unit": "mm", "min": -150, "max": 500, "step": 0.1},
    {"key": "y_brush", "macro": "TOOL_CFG", "variable": "y_brush", "label": "Brush Y", "group": "Cleaning and priming", "unit": "mm", "min": -150, "max": 500, "step": 0.1},
    {"key": "x_prime_shift", "macro": "TOOL_CFG", "variable": "x_prime_shift", "label": "Prime X shift", "group": "Cleaning and priming", "unit": "mm", "min": -50, "max": 50, "step": 0.1},
    {"key": "fast_accel", "macro": "TOOL_CFG", "variable": "fast_accel", "label": "Toolchange acceleration", "group": "Motion", "unit": "mm/s²", "min": 100, "max": 40000, "step": 100},
    {"key": "fast_speed", "macro": "TOOL_CFG", "variable": "fast_speed", "label": "Fast movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 600, "step": 1},
    {"key": "slow_speed", "macro": "TOOL_CFG", "variable": "slow_speed", "label": "Docking movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 200, "step": 1},
    {"key": "clean_speed", "macro": "TOOL_CFG", "variable": "clean_speed", "label": "Brush movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 300, "step": 1},
    {"key": "e_open", "macro": "TOOL_CFG", "variable": "e_open", "label": "Feeder open movement", "group": "Feeder", "unit": "mm", "min": -30, "max": 30, "step": 0.1},
    {"key": "e_close", "macro": "TOOL_CFG", "variable": "e_close", "label": "Feeder close movement", "group": "Feeder", "unit": "mm", "min": -30, "max": 30, "step": 0.1},
    {"key": "e_cur_high_mult", "macro": "TOOL_CFG", "variable": "e_cur_high_mult", "label": "Feeder current multiplier", "group": "Feeder", "min": 1, "max": 2.2, "step": 0.05},
    {"key": "eddy_z", "macro": "GLOBAL_STATE", "variable": "eddy_z", "label": "Additional tap Z offset", "group": "Calibration", "unit": "mm", "min": -5, "max": 5, "step": 0.01},
)


TOOL_SETTINGS: tuple[dict[str, Any], ...] = (
    {"variable": "prime_amount", "label": "Prime amount", "category": "Priming", "unit": "mm", "min": 0, "max": 100, "step": 0.1},
    {"variable": "prime_speed", "label": "Prime speed", "category": "Priming", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "prime_retract", "label": "Prime retract", "category": "Priming", "unit": "mm", "min": 0, "max": 20, "step": 0.1},
    {"variable": "prime_retract_speed", "label": "Prime retract speed", "category": "Priming", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "first_prime_flag", "label": "First prime enabled", "category": "First Prime", "type": "choice", "choices": [{"value": 1, "label": "Enabled"}, {"value": 0, "label": "Disabled"}]},
    {"variable": "first_prime_amount", "label": "First prime amount", "category": "First Prime", "unit": "mm", "min": 0, "max": 100, "step": 0.1},
    {"variable": "first_prime_speed", "label": "First prime speed", "category": "First Prime", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "clean_move", "label": "Cleaning enabled", "category": "Cleaning", "type": "choice", "choices": [{"value": 1, "label": "Enabled"}, {"value": 0, "label": "Disabled"}]},
    {"variable": "x_clean_move", "label": "Cleaning X movement", "category": "Cleaning", "unit": "mm", "min": 0, "max": 50, "step": 0.1},
    {"variable": "y_clean_move", "label": "Cleaning Y movement", "category": "Cleaning", "unit": "mm", "min": 0, "max": 50, "step": 0.1},
    {"variable": "clean_move_speed", "label": "Cleaning movement speed", "category": "Cleaning", "unit": "mm/s", "min": 1, "max": 1000, "step": 1},
    {"variable": "ptfe_clean_slow_speed", "label": "PTFE slow cleaning speed", "category": "Cleaning", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "clean_retract", "label": "Cleaning retract", "category": "Cleaning", "unit": "mm", "min": 0, "max": 20, "step": 0.1},
    {"variable": "clean_retract_speed", "label": "Cleaning retract speed", "category": "Cleaning", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
)


def schema_for(tool_count: int) -> list[dict[str, Any]]:
    setup_groups = {"Layout", "Feeder", "Calibration", "Cleaning and priming", "Motion"}
    schema = [
        {**dict(item), "page": "setup" if item["group"] in setup_groups else "tuning"}
        for item in BASE_SETTINGS
    ]
    for tool in range(tool_count):
        schema.append(
            {
                "key": f"x_t{tool}", "macro": "TOOL_CFG", "variable": f"x_t{tool}",
                "label": f"T{tool} dock X", "group": "Dock coordinates", "unit": "mm",
                "min": -100, "max": 600, "step": 0.1, "page": "setup",
            }
        )
        for template in TOOL_SETTINGS:
            definition = dict(template)
            variable = str(definition["variable"])
            definition.update({
                "key": f"t{tool}_{variable}",
                "macro": f"TOOL_STATE_{tool}",
                "group": "Tool priming and cleaning",
                "tool": tool,
                "page": "tuning",
            })
            schema.append(definition)
        for axis in ("x", "y", "z"):
            schema.append({
                "key": f"t{tool}_offset_{axis}",
                "macro": "TOOL_OFFSET",
                "variable": f"t{tool}_off_{axis}",
                "saved_variable": f"t{tool}_gcode_{axis}_offset",
                "label": f"{axis.upper()} offset",
                "group": "Tool priming and cleaning",
                "category": "Offsets",
                "unit": "mm",
                "min": -50 if axis != "z" else -10,
                "max": 50 if axis != "z" else 10,
                "step": 0.001,
                "tool": tool,
                "page": "tuning",
                "kind": "tool_offset",
            })
    return schema


def validate_setting(key: str, value: Any, tool_count: int) -> tuple[dict[str, Any], float | int]:
    definition = next((item for item in schema_for(tool_count) if item["key"] == key), None)
    if definition is None:
        raise ValueError(f"Unsupported setting: {key}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{definition['label']} must be numeric") from exc
    if numeric < float(definition.get("min", numeric)) or numeric > float(definition.get("max", numeric)):
        raise ValueError(f"{definition['label']} must be between {definition.get('min')} and {definition.get('max')}")
    if definition.get("type") == "choice":
        choices = [item["value"] for item in definition["choices"]]
        if numeric not in choices:
            raise ValueError(f"Unsupported value for {definition['label']}")
        numeric = int(numeric)
    return definition, numeric
