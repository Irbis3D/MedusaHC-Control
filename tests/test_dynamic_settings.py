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


CURRENT_CONFIG = """
[gcode_macro TOOL_CFG]
# Safe rack clearance.
variable_y_safe: 330
variable_x_t0: 45

[gcode_macro TOOL_STATE_0]
# Extrusion before printing.
variable_prime_amount: 18
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


class VariableInspectionTests(unittest.TestCase):
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
        self.assertEqual(by_key["t0_prime_amount"]["label"], "prime_amount")
        self.assertTrue(by_key["t0_x_clean_move"]["default_visible"])
        self.assertTrue(by_key["t0_ptfe_clean_slow_speed"]["default_visible"])
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

    def test_permanent_replacement_preserves_comment(self) -> None:
        text = "[gcode_macro TOOL_STATE_0]\n# User-facing description.\nvariable_prime_amount: 10 # inline\n"
        replaced = ConfigStore._replace_macro_variable(text, "TOOL_STATE_0", "prime_amount", 12.5)
        self.assertIn("# User-facing description.", replaced)
        self.assertIn("variable_prime_amount: 12.5 # inline", replaced)


class LayoutDatabaseTests(unittest.TestCase):
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
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                service.stop()


if __name__ == "__main__":
    unittest.main()
