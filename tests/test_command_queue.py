import threading
import unittest
from unittest.mock import Mock

from medusahc_control.config import AppConfig
from medusahc_control.moonraker import MoonrakerError
from medusahc_control.service import ControlService
from medusahc_control.state import normalize_status


def ready_status():
    return {"webhooks": {"state": "ready"}, "print_stats": {"state": "standby"},
            "medusahc": {"current_tool": 0, "tool_count": 2, "operation": "idle"}}


class CommandQueueTests(unittest.TestCase):
    def setUp(self):
        self.service = ControlService(AppConfig(simulate=False, allow_commands=True, database_path=":memory:"))
        self.service._moonraker = Mock()
        self.service._moonraker.query_status.return_value = ready_status()
        self.service._state = normalize_status(ready_status())

    def tearDown(self):
        self.service.stop()

    def run_queue(self):
        worker = threading.Thread(target=self.service._command_loop, daemon=True)
        worker.start()
        self.service._command_thread = worker
        # join on the queue is bounded by an event so a regression cannot hang tests.
        done = threading.Event()
        threading.Thread(target=lambda: (self.service._command_queue.join(), done.set()), daemon=True).start()
        self.assertTrue(done.wait(3), "Command queue failed to drain")

    def test_passive_then_active_does_not_resurrect_pending_actions(self):
        self.service.execute("home", {})
        self.service.set_control_mode(False)
        self.service.set_control_mode(True)
        self.assertTrue(self.service._command_queue.empty())
        self.service._moonraker.send_gcode.assert_not_called()

    def test_worker_rechecks_print_status(self):
        self.service.execute("home", {})
        self.service._moonraker.query_status.return_value["print_stats"]["state"] = "printing"
        self.run_queue()
        self.service._moonraker.send_gcode.assert_not_called()

    def test_failure_cancels_remaining_commands(self):
        self.service.execute("home", {})
        self.service.execute("home", {})
        self.service._moonraker.send_gcode.side_effect = MoonrakerError("failed")
        self.run_queue()
        self.assertEqual(self.service._moonraker.send_gcode.call_count, 1)
        self.assertEqual(self.service.state()["last_error"], "failed")

    def test_restart_cancels_pending_commands(self):
        self.service.execute("home", {})
        self.service.execute("restart_klipper", {})
        self.assertTrue(self.service._command_queue.empty())
        self.service._moonraker.restart_klipper.assert_called_once()

    def test_calibration_blocks_motion_until_idle(self):
        status = ready_status()
        status["medusahc_calibrate"] = {"operation": "calibrating_eddy"}
        state = normalize_status(status)
        self.assertEqual(state["operation"], "calibrating_eddy")
        for capability in ("can_home", "can_jog", "can_select", "can_clean", "can_feeder", "can_calibrate"):
            self.assertFalse(state["capabilities"][capability])

    def test_valid_action_executes(self):
        self.service.execute("home", {})
        self.run_queue()
        self.service._moonraker.send_gcode.assert_called_once()
