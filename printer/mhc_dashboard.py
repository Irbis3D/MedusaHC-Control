"""Read-only MedusaHC status adapter for Klipper/Moonraker.

Install this file in klippy/extras and add [mhc_dashboard] to printer.cfg.
It observes the existing pin_watch object and does not execute G-code or change
pin state.
"""


class MHCDashboard:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.pin_watch_name = config.get("pin_watch", "pin_watch io")
        self.pin_watch = None
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        self.pin_watch = self.printer.lookup_object(self.pin_watch_name, None)

    def get_status(self, eventtime):
        source = self.pin_watch
        if source is None:
            source = self.printer.lookup_object(self.pin_watch_name, None)
        if source is None:
            return {
                "current_tool": -2,
                "tool_count": 0,
                "sensor_error": True,
                "sensors": {},
            }
        raw_state = getattr(source, "state", {}) or {}
        sensors = {}
        for name, value in raw_state.items():
            try:
                sensors[str(name)] = int(value)
            except (TypeError, ValueError):
                continue
        current_tool = int(getattr(source, "current_tool", -2))
        tool_indices = []
        for name in sensors:
            if name.startswith("t"):
                try:
                    tool_indices.append(int(name[1:]))
                except ValueError:
                    pass
        tool_count = max(tool_indices) + 1 if tool_indices else 0
        return {
            "current_tool": current_tool,
            "tool_count": tool_count,
            "sensor_error": current_tool == -2,
            "sensors": sensors,
        }


def load_config(config):
    return MHCDashboard(config)

