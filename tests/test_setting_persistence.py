import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from medusahc_control.config import AppConfig
from medusahc_control.moonraker import MoonrakerError
from medusahc_control.service import ControlService, SafetyError
from medusahc_control.state import normalize_status


class SettingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "MHC_variables.cfg"
        self.path.write_text("[gcode_macro _TOOL_STATE_0]\nvariable_prime_amount: 10\ngcode:\n")
        self.service = ControlService(AppConfig(
            simulate=False, allow_commands=True,
            database_path=str(Path(self.temporary.name) / "stats.db"),
            medusahc_variables_path=str(self.path)))
        self.service._moonraker = Mock()
        self.service._state = normalize_status({
            "webhooks": {"state": "ready"},
            "medusahc": {"current_tool": 0, "tool_count": 1},
            "gcode_macro _TOOL_STATE_0": {"prime_amount": 10}})

    def tearDown(self):
        self.service.stop()
        self.temporary.cleanup()

    def test_backup_permission_failure_does_not_apply_value(self):
        with patch.object(self.service._config_store, "_backup", side_effect=PermissionError("backups")):
            with self.assertRaisesRegex(SafetyError, "not saved or applied"):
                self.service.set_setting("t0_prime_amount", 20, "permanent")
        self.service._moonraker.send_gcode.assert_not_called()
        self.assertIn("prime_amount: 10", self.path.read_text())
        self.assertEqual(self.service.settings_payload()["values"]["t0_prime_amount"], 10)

    def test_save_precedes_apply_and_addresses_actual_hidden_macro(self):
        def send(script):
            self.assertIn("prime_amount: 20", self.path.read_text())
            self.assertIn("MACRO=_TOOL_STATE_0 VARIABLE=prime_amount VALUE=20", script)
        self.service._moonraker.send_gcode.side_effect = send
        self.service.set_setting("t0_prime_amount", 20, "permanent")
        backups = list((Path(self.temporary.name) / "backups").glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertIn("prime_amount: 10", backups[0].read_text())
        self.assertEqual(self.service.settings_payload()["values"]["t0_prime_amount"], 20)

    def test_apply_failure_reports_that_file_was_saved(self):
        self.service._moonraker.send_gcode.side_effect = MoonrakerError("disconnected")
        with self.assertRaisesRegex(SafetyError, "saved, but applying"):
            self.service.set_setting("t0_prime_amount", 20, "permanent")
        self.assertIn("prime_amount: 20", self.path.read_text())

    def test_file_edit_is_reread_without_faking_running_value(self):
        self.path.write_text("[gcode_macro _TOOL_STATE_0]\nvariable_prime_amount: 25\ngcode:\n")
        payload = self.service.settings_payload()
        definition = next(item for item in payload["schema"] if item["key"] == "t0_prime_amount")
        self.assertEqual(definition["configured_value"], 25)
        self.assertEqual(payload["values"]["t0_prime_amount"], 10)

    def test_apply_does_not_save_configuration(self):
        self.service.set_setting("t0_prime_amount", 20, "runtime")
        self.assertIn("prime_amount: 10", self.path.read_text())
        self.assertEqual(self.service.settings_payload()["values"]["t0_prime_amount"], 20)
