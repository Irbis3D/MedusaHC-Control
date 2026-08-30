from __future__ import annotations

import tempfile
import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from medusahc_control.config_store import ConfigStore
from medusahc_control.config import AppConfig
from medusahc_control.database import StatsDatabase
from medusahc_control.service import ControlService
from medusahc_control.server import MedusaHTTPServer
from medusahc_control.settings import inspect_variable_config, schema_for
from medusahc_control.state import normalize_status


CURRENT_CONFIG = """
[gcode_macro TOOL_CFG]
# Safe rack clearance.
variable_y_safe: 330
variable_x_t0: 45
variable_servo_open_angle: 180
variable_servo_close_angle: 0

[gcode_macro TOOL_STATE_0]
# Extrusion before printing.
variable_prime_amount: 18
variable_first_prime_enabled: 1
variable_first_prime_flag: 0
variable_x_clean_move: 4
variable_y_clean_move: 5
# PTFE cleaning speed.
variable_ptfe_clean_slow_speed: 2
variable_internal_counter: 0
"""


OLD_CONFIG = """
[gcode_macro TOOL_CFG]
variable_y_safe: 330
variable_x_t0: 45

[gcode_macro GLOBAL_STATE]
# Shared prime for old configurations.
variable_prime_amount: 15

[gcode_macro TOOL_STATE_0]
# Old X brush movement.
variable_clean_move_x: 4
variable_clean_move_y: 5
variable_prime_speed: 5
"""


INTERNAL_CONFIG = """
[gcode_macro TOOL_CFG]
variable_fast_speed: 300
variable_slow_speed: 40
variable_clean_speed: 50

[gcode_macro GLOBAL_STATE]
#------------- Do not change ---------------
variable_eddy_z: 0
variable_layer: 0
variable_fast_feedrate: 0
variable_slow_feedrate: 0
variable_clean_feedrate: 0

[gcode_macro TOOL_STATE_0]
variable_prime_amount: 13
"""


class VariableInspectionTests(unittest.TestCase):
    def test_hidden_macro_sections_keep_canonical_panel_names(self) -> None:
        hidden = """
[gcode_macro _TOOL_CFG]
variable_y_safe: 321
[gcode_macro _GLOBAL_STATE]
variable_max_tool: 1
[gcode_macro _TOOL_STATE_0]
variable_prime_amount: 17
[gcode_macro _TOOL_OFFSET]
variable_t0_off_x: 0.125
"""
        discovered = inspect_variable_config(hidden)
        self.assertEqual(discovered[("TOOL_CFG", "y_safe")]["source_macro"], "_TOOL_CFG")
        schema = schema_for(1, discovered)
        by_key = {item["key"]: item for item in schema}
        self.assertTrue(by_key["y_safe"]["available"])
        self.assertEqual(by_key["y_safe"]["source_macro"], "_TOOL_CFG")
        self.assertEqual(by_key["t0_offset_x"]["source_macro"], "_TOOL_OFFSET")

    def test_permanent_write_uses_hidden_source_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MHC_variables.cfg"
            path.write_text("[gcode_macro _TOOL_CFG]\nvariable_y_safe: 300\n", encoding="utf-8")
            store = ConfigStore(str(path), Path(directory) / "backups")
            metadata = store.inspect_variables()[("TOOL_CFG", "y_safe")]
            store.save_permanent({
                "macro": "TOOL_CFG",
                "source_macro": metadata["source_macro"],
                "variable": "y_safe",
            }, 315)
            self.assertIn("variable_y_safe: 315", path.read_text(encoding="utf-8"))

    def test_direct_comments_are_descriptions(self) -> None:
        discovered = inspect_variable_config(CURRENT_CONFIG)
        self.assertEqual(discovered[("TOOL_CFG", "y_safe")]["description"], "Safe rack clearance.")
        self.assertEqual(discovered[("TOOL_STATE_0", "prime_amount")]["description"], "Extrusion before printing.")
        self.assertEqual(discovered[("TOOL_STATE_0", "x_clean_move")]["description"], "")

    def test_current_config_has_default_modern_layout(self) -> None:
        schema = schema_for(1, inspect_variable_config(CURRENT_CONFIG))
        by_key = {item["key"]: item for item in schema}
        self.assertTrue(by_key["t0_prime_amount"]["available"])
        self.assertEqual(by_key["t0_prime_amount"]["configured_value"], 18)
        self.assertEqual(by_key["y_safe"]["configured_value"], 330)
        self.assertEqual(by_key["servo_open_angle"]["configured_value"], 180)
        self.assertEqual(by_key["servo_close_angle"]["configured_value"], 0)
        self.assertEqual(by_key["servo_open_angle"]["group"], "Feeder")
        self.assertEqual(by_key["t0_prime_amount"]["label"], "prime_amount")
        self.assertTrue(by_key["t0_x_clean_move"]["default_visible"])
        self.assertTrue(by_key["t0_ptfe_clean_slow_speed"]["default_visible"])
        self.assertTrue(by_key["t0_first_prime_enabled"]["default_visible"])
        self.assertFalse(by_key["t0_first_prime_flag"]["default_visible"])
        self.assertFalse(by_key["t0_internal_counter"]["default_visible"])

    def test_old_config_discovers_old_names_without_crashing(self) -> None:
        schema = schema_for(1, inspect_variable_config(OLD_CONFIG))
        by_key = {item["key"]: item for item in schema}
        self.assertTrue(by_key["t0_clean_move_x"]["available"])
        self.assertTrue(by_key["t0_clean_move_x"]["default_visible"])
        self.assertNotIn("t0_x_clean_move", by_key)
        self.assertEqual(by_key["global_prime_amount"]["group"], "Shared Priming")

    def test_missing_expected_variable_is_disabled_with_reason(self) -> None:
        schema = schema_for(1, inspect_variable_config("[gcode_macro TOOL_STATE_0]\nvariable_prime_amount: 2\n"))
        definition = next(item for item in schema if item["key"] == "y_safe")
        self.assertFalse(definition["available"])
        self.assertIn("variable_y_safe", definition["availability_reason"])

    def test_do_not_change_block_is_available_but_hidden_by_default(self) -> None:
        discovered = inspect_variable_config(INTERNAL_CONFIG)
        self.assertTrue(discovered[("GLOBAL_STATE", "clean_feedrate")]["internal"])
        self.assertFalse(discovered[("TOOL_STATE_0", "prime_amount")]["internal"])

        schema = schema_for(1, discovered)
        by_key = {item["key"]: item for item in schema}
        self.assertTrue(by_key["eddy_z"]["available"])
        self.assertFalse(by_key["eddy_z"]["default_visible"])
        self.assertTrue(by_key["global_clean_feedrate"]["available"])
        self.assertFalse(by_key["global_clean_feedrate"]["default_visible"])
        self.assertTrue(by_key["t0_prime_amount"]["default_visible"])

    def test_permanent_replacement_preserves_comment(self) -> None:
        text = "[gcode_macro TOOL_STATE_0]\n# User-facing description.\nvariable_prime_amount: 10 # inline\n"
        replaced = ConfigStore._replace_macro_variable(text, "TOOL_STATE_0", "prime_amount", 12.5)
        self.assertIn("# User-facing description.", replaced)
        self.assertIn("variable_prime_amount: 12.5 # inline", replaced)


class LayoutDatabaseTests(unittest.TestCase):
    def test_hidden_runtime_objects_are_normalized_and_written_by_real_name(self) -> None:
        status = {
            "webhooks": {"state": "ready"},
            "print_stats": {"state": "standby"},
            "toolhead": {"homed_axes": "xyz", "position": [0, 0, 0, 0]},
            "pin_watch io": {"current_tool": -1, "tool_count": 1},
            "gcode_macro _GLOBAL_STATE": {"max_tool": 1},
            "gcode_macro _TOOL_CFG": {"tools_direction": 1, "y_safe": 300},
            "gcode_macro _TOOL_OFFSET": {"t0_off_x": 0.1, "t0_off_y": 0, "t0_off_z": 0},
            "gcode_macro _TOOL_STATE_0": {"prime_amount": 12},
            "gcode_macro T0": {},
            "extruder": {},
        }
        normalized = normalize_status(status)
        self.assertEqual(normalized["tool_count"], 1)
        self.assertEqual(normalized["macro_values"]["TOOL_CFG"]["y_safe"], 300)
        self.assertEqual(normalized["macro_names"]["TOOL_STATE_0"], "_TOOL_STATE_0")
        definition = {
            "macro": "TOOL_CFG", "runtime_macro": "_TOOL_CFG", "variable": "y_safe"
        }
        self.assertEqual(
            ControlService._runtime_command_updates(definition, 310),
            [("_TOOL_CFG", "y_safe", 310.0)],
        )

    def test_calibration_commands_support_new_and_legacy_modules(self) -> None:
        modern = {"available_macros": ["CALIBRATE_XYZ_TOUCH", "CALIBRATE_XYZ_EDDY", "CALIBRATE_Z_EDDY"]}
        self.assertEqual(ControlService._gcode("calibrate_xyz_touch", {}, modern), "CALIBRATE_XYZ_TOUCH")
        self.assertEqual(ControlService._gcode("calibrate_xyz_eddy", {}, modern), "CALIBRATE_XYZ_EDDY")
        self.assertEqual(ControlService._gcode("calibrate_z_eddy", {}, modern), "CALIBRATE_Z_EDDY")
        self.assertEqual(ControlService._gcode("calibrate_xyz_touch", {}, {}), "CALIBRATE_AND_SAVE_OFFSETS")
        self.assertEqual(ControlService._gcode("calibrate_z_eddy", {}, {}), "TOOL_Z_CALIBRATION")

    def test_stats_ignore_transient_sensor_error_during_successful_change(self) -> None:
        database = StatsDatabase(":memory:")
        try:
            database.observe({"current_tool": 0, "print_state": "printing", "last_error": ""})
            database.observe({"current_tool": -2, "print_state": "printing", "last_error": "", "operation": "dropping"})
            database.observe({"current_tool": -1, "print_state": "printing", "last_error": "", "operation": "dropping"})
            database.observe({"current_tool": -2, "print_state": "printing", "last_error": "", "operation": "picking"})
            database.observe({"current_tool": 1, "print_state": "printing", "last_error": "", "operation": "idle"})
            summary = database.summary()
            self.assertEqual(summary["totals"]["toolchange_failed"], 0)
            self.assertEqual(summary["totals"]["tool_park"], 1)
            self.assertEqual(summary["totals"]["tool_pickup"], 1)
        finally:
            database.close()

    def test_stats_record_each_controller_error_once(self) -> None:
        database = StatsDatabase(":memory:")
        try:
            database.observe({"current_tool": 0, "print_state": "printing", "last_error": "", "target_tool": 1})
            failed = {
                "current_tool": -2,
                "print_state": "paused",
                "last_error": "MHC_SET: sensors did not confirm T1",
                "operation": "idle",
                "target_tool": 1,
            }
            database.observe(failed)
            database.observe(failed)
            summary = database.summary()
            self.assertEqual(summary["totals"]["toolchange_failed"], 1)
            self.assertEqual(summary["per_tool"][0]["tool"], 1)
            self.assertEqual(summary["per_tool"][0]["errors"], 1)
            self.assertEqual(summary["recent"][0]["details"]["message"], failed["last_error"])
        finally:
            database.close()

    def test_speed_apply_updates_source_and_runtime_feedrate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ControlService(AppConfig(
                simulate=True,
                database_path=str(Path(directory) / "stats.db"),
            ))
            try:
                definition = next(
                    item for item in service.settings_payload()["schema"]
                    if item["key"] == "fast_speed"
                )
                self.assertEqual(definition["active_runtime_targets"], [{
                    "macro": "GLOBAL_STATE",
                    "variable": "fast_feedrate",
                    "multiplier": 60,
                }])
                service.set_setting("fast_speed", 275, "runtime")
                state = service.state()
                self.assertEqual(state["macro_values"]["TOOL_CFG"]["fast_speed"], 275)
                self.assertEqual(state["macro_values"]["GLOBAL_STATE"]["fast_feedrate"], 16500)
            finally:
                service.stop()

    def test_speed_apply_skips_missing_legacy_runtime_feedrate(self) -> None:
        definition = {
            "macro": "TOOL_CFG",
            "variable": "fast_speed",
            "active_runtime_targets": [],
        }
        self.assertEqual(
            ControlService._runtime_setting_updates(definition, 300),
            [("TOOL_CFG", "fast_speed", 300.0)],
        )

    def test_stale_poll_cannot_overwrite_just_applied_runtime_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ControlService(AppConfig(
                simulate=True,
                database_path=str(Path(directory) / "stats.db"),
            ))
            try:
                definition = {"macro": "TOOL_STATE_0", "variable": "clean_move"}
                service._remember_runtime_setting(definition, 0)
                stale = {"macro_values": {"TOOL_STATE_0": {"clean_move": 1}}}
                with service._state_lock:
                    service._merge_runtime_setting_overrides(stale)
                self.assertEqual(stale["macro_values"]["TOOL_STATE_0"]["clean_move"], 0)

                observed = {"macro_values": {"TOOL_STATE_0": {"clean_move": 0}}}
                with service._state_lock:
                    service._merge_runtime_setting_overrides(observed)
                self.assertFalse(service._runtime_setting_overrides)
            finally:
                service.stop()

    def test_runtime_reset_source_remains_saved_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ControlService(AppConfig(
                simulate=True,
                database_path=str(Path(directory) / "stats.db"),
            ))
            try:
                initial = service.settings_payload()
                offset = next(item for item in initial["schema"] if item["key"] == "t0_offset_x")
                self.assertEqual(offset["configured_value"], 0)

                service.set_setting("t0_offset_x", 1.25, "runtime")
                temporary = service.settings_payload()
                offset = next(item for item in temporary["schema"] if item["key"] == "t0_offset_x")
                self.assertEqual(temporary["values"]["t0_offset_x"], 1.25)
                self.assertEqual(offset["configured_value"], 0)

                service.set_setting("t0_offset_x", 0, "runtime")
                restored = service.settings_payload()
                self.assertEqual(restored["values"]["t0_offset_x"], 0)
            finally:
                service.stop()

    def test_tool_test_action_calls_configured_macro(self) -> None:
        self.assertEqual(ControlService._gcode("test_tools", {}), "TEST_TOOLS")
        with tempfile.TemporaryDirectory() as directory:
            service = ControlService(AppConfig(
                simulate=True,
                database_path=str(Path(directory) / "stats.db"),
            ))
            self.assertTrue(service.execute("test_tools", {})["ok"])
            service.stop()

    def test_layout_defaults_customizes_and_resets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = StatsDatabase(str(Path(directory) / "stats.db"))
            self.assertFalse(database.settings_layout()["customized"])
            layout = database.save_settings_layout([
                {"layout_key": "tool:prime_amount", "position": 0, "description": "Local text"},
            ])
            self.assertTrue(layout["customized"])
            self.assertEqual(layout["entries"][0]["description"], "Local text")
            self.assertFalse(database.reset_settings_layout()["customized"])
            database.close()

    def test_custom_layout_survives_service_update_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "stats.db")
            first = ControlService(AppConfig(simulate=True, database_path=database_path))
            first.save_settings_layout([
                {"layout_key": "tool:prime_amount", "description": "My retained field"},
                {"layout_key": "tool:clean_retract", "description": "Second retained field"},
            ])
            first.stop()

            updated = ControlService(AppConfig(simulate=True, database_path=database_path))
            try:
                payload = updated.settings_payload()
                visible = {
                    item["layout_key"]: item["description"]
                    for item in payload["schema"]
                    if item["visible"]
                }
                self.assertEqual(visible, {
                    "tool:prime_amount": "My retained field",
                    "tool:clean_retract": "Second retained field",
                })
            finally:
                updated.stop()

    def test_service_starts_with_modern_layout_and_can_customize_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = ControlService(AppConfig(
                simulate=True,
                database_path=str(Path(directory) / "stats.db"),
            ))
            payload = service.settings_payload()
            visible = [item for item in payload["schema"] if item["visible"]]
            self.assertTrue(any(item["variable"] == "prime_amount" for item in visible))
            self.assertTrue(any(item["variable"] == "x_clean_move" for item in visible))
            service.save_settings_layout([
                {"layout_key": "tool:prime_amount", "description": "Custom description"},
            ])
            customized = service.settings_payload()
            self.assertEqual(
                {item["layout_key"] for item in customized["schema"] if item["visible"]},
                {"tool:prime_amount"},
            )
            self.assertTrue(all(
                item["description"] == "Custom description"
                for item in customized["schema"]
                if item["visible"]
            ))
            service.reset_settings_layout()
            self.assertGreater(
                sum(item["visible"] for item in service.settings_payload()["schema"]),
                1,
            )
            service.stop()

    def test_layout_http_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(simulate=True, database_path=str(Path(directory) / "stats.db"))
            service = ControlService(config)
            server = MedusaHTTPServer(("127.0.0.1", 0), service, config)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base_url}/api/settings", timeout=3) as response:
                    payload = json.load(response)
                self.assertTrue(any(item["visible"] for item in payload["schema"]))
                request = Request(
                    f"{base_url}/api/settings/layout",
                    data=json.dumps({"entries": [{"layout_key": "tool:prime_amount"}]}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    self.assertTrue(json.load(response)["ok"])
                with urlopen(f"{base_url}/api/settings", timeout=3) as response:
                    customized = json.load(response)
                self.assertEqual(
                    {item["layout_key"] for item in customized["schema"] if item["visible"]},
                    {"tool:prime_amount"},
                )
                with urlopen(f"{base_url}/medusahc/", timeout=3) as response:
                    html = response.read().decode("utf-8")
                self.assertIn('href="styles.css"', html)
                with urlopen(f"{base_url}/medusahc/styles.css", timeout=3) as response:
                    self.assertEqual(response.status, 200)
                with urlopen(f"{base_url}/medusahc/api/settings", timeout=3) as response:
                    prefixed = json.load(response)
                self.assertEqual(
                    {item["layout_key"] for item in prefixed["schema"] if item["visible"]},
                    {"tool:prime_amount"},
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                service.stop()


if __name__ == "__main__":
    unittest.main()
