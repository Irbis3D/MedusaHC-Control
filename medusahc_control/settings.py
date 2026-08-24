from __future__ import annotations

import math
import re
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
    {"key": "fast_speed", "macro": "TOOL_CFG", "variable": "fast_speed", "label": "Fast movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 600, "step": 1, "runtime_targets": [{"macro": "GLOBAL_STATE", "variable": "fast_feedrate", "multiplier": 60}]},
    {"key": "slow_speed", "macro": "TOOL_CFG", "variable": "slow_speed", "label": "Docking movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 200, "step": 1, "runtime_targets": [{"macro": "GLOBAL_STATE", "variable": "slow_feedrate", "multiplier": 60}]},
    {"key": "clean_speed", "macro": "TOOL_CFG", "variable": "clean_speed", "label": "Brush movement", "group": "Motion", "unit": "mm/s", "min": 1, "max": 300, "step": 1, "runtime_targets": [{"macro": "GLOBAL_STATE", "variable": "clean_feedrate", "multiplier": 60}]},
    {"key": "e_open", "macro": "TOOL_CFG", "variable": "e_open", "label": "Feeder open movement", "group": "Feeder", "unit": "mm", "min": -30, "max": 30, "step": 0.1},
    {"key": "e_close", "macro": "TOOL_CFG", "variable": "e_close", "label": "Feeder close movement", "group": "Feeder", "unit": "mm", "min": -30, "max": 30, "step": 0.1},
    {"key": "e_cur_high_mult", "macro": "TOOL_CFG", "variable": "e_cur_high_mult", "label": "Feeder current multiplier", "group": "Feeder", "min": 1, "max": 2.2, "step": 0.05},
    {"key": "eddy_z", "macro": "GLOBAL_STATE", "variable": "eddy_z", "label": "Additional tap Z offset", "group": "Calibration", "unit": "mm", "min": -5, "max": 5, "step": 0.01},
)


TOOL_SETTINGS: tuple[dict[str, Any], ...] = (
    {"variable": "prime_amount", "category": "Priming", "unit": "mm", "min": 0, "max": 100, "step": 0.1},
    {"variable": "prime_speed", "category": "Priming", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "prime_retract", "category": "Priming", "unit": "mm", "min": 0, "max": 20, "step": 0.1},
    {"variable": "prime_retract_speed", "category": "Priming", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "first_prime_enabled", "category": "First Prime", "type": "choice", "choices": [{"value": 1, "label": "Enabled"}, {"value": 0, "label": "Disabled"}]},
    {"variable": "first_prime_flag", "category": "First Prime"},
    {"variable": "first_prime_amount", "category": "First Prime", "unit": "mm", "min": 0, "max": 100, "step": 0.1},
    {"variable": "first_prime_speed", "category": "First Prime", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "clean_move", "category": "Cleaning", "type": "choice", "choices": [{"value": 1, "label": "Enabled"}, {"value": 0, "label": "Disabled"}]},
    {"variable": "x_clean_move", "category": "Cleaning", "unit": "mm", "min": 0, "max": 50, "step": 0.1},
    {"variable": "y_clean_move", "category": "Cleaning", "unit": "mm", "min": 0, "max": 50, "step": 0.1},
    {"variable": "clean_move_speed", "category": "Cleaning", "unit": "mm/s", "min": 1, "max": 1000, "step": 1},
    {"variable": "ptfe_clean_slow_speed", "category": "Cleaning", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
    {"variable": "clean_retract", "category": "Cleaning", "unit": "mm", "min": 0, "max": 20, "step": 0.1},
    {"variable": "clean_retract_speed", "category": "Cleaning", "unit": "mm/s", "min": 0.1, "max": 100, "step": 0.1},
)

LEGACY_TOOL_EQUIVALENTS: dict[str, set[str]] = {
    "x_clean_move": {"clean_move_x"},
    "y_clean_move": {"clean_move_y"},
}


_SECTION_RE = re.compile(r"^\s*\[gcode_macro\s+([^\]]+)]\s*(?:#.*)?$", re.IGNORECASE)
_VARIABLE_RE = re.compile(r"^\s*variable_([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^#\r\n]*?)(?:\s+#.*)?$")
_COMMENT_RE = re.compile(r"^\s*#\s?(.*)$")


def inspect_variable_config(text: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Return active gcode macro variables and directly preceding comments."""
    discovered: dict[tuple[str, str], dict[str, Any]] = {}
    macro = ""
    pending_comments: list[str] = []
    internal_block = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        section_match = _SECTION_RE.match(line)
        if section_match:
            macro = section_match.group(1).strip()
            pending_comments = []
            internal_block = False
            continue
        if not macro:
            continue
        comment_match = _COMMENT_RE.match(line)
        if comment_match:
            comment = comment_match.group(1).strip()
            if re.search(r"\bdo\s+not\s+(?:change|edit)\b", comment, re.IGNORECASE):
                internal_block = True
                pending_comments = []
                continue
            pending_comments.append(comment)
            continue
        if not line.strip():
            pending_comments = []
            continue
        variable_match = _VARIABLE_RE.match(line)
        if not variable_match:
            pending_comments = []
            continue
        variable, raw_value = variable_match.groups()
        numeric_value = _numeric_literal(raw_value.strip())
        discovered[(macro, variable)] = {
            "macro": macro,
            "variable": variable,
            "raw_value": raw_value.strip(),
            "numeric_value": numeric_value,
            "description": "\n".join(item for item in pending_comments if item).strip(),
            "internal": internal_block,
            "line": line_number,
        }
        pending_comments = []
    return discovered


def schema_for(
    tool_count: int,
    discovered: dict[tuple[str, str], dict[str, Any]] | None = None,
    discovery_error: str = "",
) -> list[dict[str, Any]]:
    """Build a stable machine schema plus discovered tool process variables."""
    setup_groups = {"Layout", "Feeder", "Calibration", "Cleaning and priming", "Motion"}
    schema = [
        _with_availability(
            {
                **dict(item),
                "label": str(item["variable"]),
                "page": "setup" if item["group"] in setup_groups else "tuning",
            },
            discovered,
            discovery_error,
        )
        for item in BASE_SETTINGS
    ]
    for tool in range(tool_count):
        schema.append(
            _with_availability(
                {
                    "key": f"x_t{tool}", "macro": "TOOL_CFG", "variable": f"x_t{tool}",
                    "label": f"x_t{tool}", "group": "Dock coordinates", "unit": "mm",
                    "min": -100, "max": 600, "step": 0.1, "page": "setup",
                },
                discovered,
                discovery_error,
            )
        )

    if discovered is None:
        for tool in range(tool_count):
            for template in TOOL_SETTINGS:
                schema.append(_tool_definition(tool, dict(template), available=True))
    else:
        known = {str(item["variable"]): dict(item) for item in TOOL_SETTINGS}
        for tool in range(tool_count):
            macro = f"TOOL_STATE_{tool}"
            found_names: set[str] = set()
            for (found_macro, variable), metadata in discovered.items():
                category = _tuning_category(variable)
                if found_macro != macro:
                    continue
                if metadata.get("numeric_value") is None:
                    continue
                template = dict(known.get(variable, {"variable": variable, "category": category or "Other", "step": 0.1}))
                template["description"] = str(metadata.get("description", ""))
                definition = _tool_definition(tool, template, available=True)
                definition["configured_value"] = metadata.get("numeric_value")
                definition["internal"] = bool(metadata.get("internal")) or variable == "first_prime_flag"
                definition["default_visible"] = category is not None and not definition["internal"]
                schema.append(definition)
                found_names.add(variable)
            for template in TOOL_SETTINGS:
                variable = str(template["variable"])
                if variable in found_names or LEGACY_TOOL_EQUIVALENTS.get(variable, set()) & found_names:
                    continue
                definition = _tool_definition(tool, dict(template), available=False)
                definition["availability_reason"] = _missing_reason(macro, variable, discovery_error)
                schema.append(definition)

        for (macro, variable), metadata in discovered.items():
            category = _tuning_category(variable)
            if macro != "GLOBAL_STATE" or category is None or metadata.get("numeric_value") is None:
                continue
            template = dict(known.get(variable, {"variable": variable, "category": category, "step": 0.1}))
            template.update({
                "key": f"global_{variable}",
                "macro": macro,
                "label": variable,
                "group": f"Shared {category}",
                "page": "tuning",
                "description": str(metadata.get("description", "")),
                "configured_value": metadata.get("numeric_value"),
                "internal": bool(metadata.get("internal")),
                "available": True,
                "legacy_shared": True,
                "layout_key": f"macro:{macro}:{variable}",
                "default_visible": not bool(metadata.get("internal")),
            })
            schema.append(template)

    for tool in range(tool_count):
        for axis in ("x", "y", "z"):
            schema.append({
                "key": f"t{tool}_offset_{axis}",
                "macro": "TOOL_OFFSET",
                "variable": f"t{tool}_off_{axis}",
                "saved_variable": f"t{tool}_gcode_{axis}_offset",
                "label": f"t{tool}_off_{axis}",
                "group": "Tool priming and cleaning",
                "category": "Offsets",
                "unit": "mm",
                "min": -50 if axis != "z" else -10,
                "max": 50 if axis != "z" else 10,
                "step": 0.001,
                "tool": tool,
                "page": "tuning",
                "kind": "tool_offset",
                "layout_key": f"tool_offset:{axis}",
                "default_visible": True,
                "available": True,
            })
    if discovered is not None:
        represented = {(str(item["macro"]), str(item["variable"])) for item in schema}
        for (macro, variable), metadata in discovered.items():
            if (macro, variable) in represented or metadata.get("numeric_value") is None:
                continue
            if re.fullmatch(r"TOOL_STATE_\d+", macro):
                continue
            schema.append({
                "key": f"advanced_{_key_fragment(macro)}_{variable}",
                "macro": macro,
                "variable": variable,
                "label": variable,
                "group": "Advanced variables",
                "page": "setup",
                "step": 0.1,
                "description": str(metadata.get("description", "")),
                "configured_value": metadata.get("numeric_value"),
                "internal": bool(metadata.get("internal")),
                "available": True,
                "layout_key": f"macro:{macro}:{variable}",
                "default_visible": False,
                "advanced": True,
            })
    return schema


def validate_setting(
    key: str,
    value: Any,
    schema: list[dict[str, Any]],
) -> tuple[dict[str, Any], float | int]:
    definition = next((item for item in schema if item["key"] == key), None)
    if definition is None:
        raise ValueError(f"Unsupported setting: {key}")
    if not definition.get("available", True):
        raise ValueError(str(definition.get("availability_reason") or f"{key} is not available"))
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{definition['label']} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{definition['label']} must be a finite number")
    if "min" in definition and numeric < float(definition["min"]):
        raise ValueError(f"{definition['label']} must be at least {definition['min']}")
    if "max" in definition and numeric > float(definition["max"]):
        raise ValueError(f"{definition['label']} must be no more than {definition['max']}")
    if definition.get("type") == "choice":
        choices = [item["value"] for item in definition["choices"]]
        if numeric not in choices:
            raise ValueError(f"Unsupported value for {definition['label']}")
        numeric = int(numeric)
    return definition, numeric


def _tool_definition(tool: int, template: dict[str, Any], *, available: bool) -> dict[str, Any]:
    variable = str(template["variable"])
    definition = dict(template)
    definition.update({
        "key": f"t{tool}_{variable}",
        "macro": f"TOOL_STATE_{tool}",
        "label": variable,
        "group": "Tool priming and cleaning",
        "tool": tool,
        "page": "tuning",
        "available": available,
        "layout_key": f"tool:{variable}",
        "default_visible": True,
    })
    definition.setdefault("description", "")
    return definition


def _with_availability(
    definition: dict[str, Any],
    discovered: dict[tuple[str, str], dict[str, Any]] | None,
    discovery_error: str,
) -> dict[str, Any]:
    result = dict(definition)
    result.setdefault("layout_key", f"macro:{result['macro']}:{result['variable']}")
    result.setdefault("default_visible", True)
    if discovered is None:
        result["available"] = True
        return result
    macro, variable = str(result["macro"]), str(result["variable"])
    result["available"] = (macro, variable) in discovered
    if result["available"] and discovered[(macro, variable)].get("description"):
        result.setdefault("description", str(discovered[(macro, variable)]["description"]))
    if result["available"]:
        metadata = discovered[(macro, variable)]
        result["configured_value"] = metadata.get("numeric_value")
        result["internal"] = bool(metadata.get("internal"))
        if result["internal"]:
            result["default_visible"] = False
    if not result["available"]:
        result["availability_reason"] = _missing_reason(macro, variable, discovery_error)
    return result


def _missing_reason(macro: str, variable: str, discovery_error: str = "") -> str:
    if discovery_error:
        return discovery_error
    return f"variable_{variable} was not found in [gcode_macro {macro}]"


def _tuning_category(variable: str) -> str | None:
    lowered = variable.lower()
    if "first_prime" in lowered:
        return "First Prime"
    if "prime" in lowered:
        return "Priming"
    if "clean" in lowered:
        return "Cleaning"
    return None


def _numeric_literal(raw_value: str) -> float | int | None:
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _key_fragment(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
