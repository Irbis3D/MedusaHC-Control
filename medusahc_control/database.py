from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


TOOLCHANGE_EVENTS = ("tool_pickup", "tool_park", "toolchange_failed")


class StatsDatabase:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._last_state: tuple[int, bool, str] | None = None
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    tool INTEGER,
                    success INTEGER NOT NULL DEFAULT 1,
                    details TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS stats_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS setting_history (
                    id INTEGER PRIMARY KEY,
                    created_at REAL NOT NULL,
                    setting_key TEXT NOT NULL,
                    value REAL NOT NULL,
                    mode TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO stats_meta(key, value) VALUES ('started_at', ?)",
                (str(time.time()),),
            )
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_events_type_tool ON events(event_type, tool)")
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_setting_history_key_id ON setting_history(setting_key, id DESC)"
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings_layout (
                    layout_key TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    description TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._connection.execute("PRAGMA optimize")

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record(self, event_type: str, *, tool: int | None = None, success: bool = True, details: dict[str, Any] | None = None) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO events(created_at, event_type, tool, success, details) VALUES (?, ?, ?, ?, ?)",
                (time.time(), event_type, tool, 1 if success else 0, json.dumps(details or {}, separators=(",", ":"))),
            )

    def record_setting(self, key: str, value: float | int, mode: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO setting_history(created_at, setting_key, value, mode) VALUES (?, ?, ?, ?)",
                (time.time(), key, float(value), mode),
            )
            self._connection.execute(
                """
                DELETE FROM setting_history
                WHERE setting_key = ? AND id NOT IN (
                    SELECT id FROM setting_history
                    WHERE setting_key = ? ORDER BY id DESC LIMIT 10
                )
                """,
                (key, key),
            )

    def setting_history(self, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        history: dict[str, list[dict[str, Any]]] = {}
        with self._lock:
            rows = self._connection.execute(
                f"SELECT setting_key, value, mode, created_at FROM setting_history WHERE setting_key IN ({placeholders}) ORDER BY id DESC",
                keys,
            )
            for row in rows:
                history.setdefault(str(row["setting_key"]), []).append({
                    "value": row["value"],
                    "mode": row["mode"],
                    "created_at": row["created_at"],
                })
        return history

    def settings_layout(self) -> dict[str, Any]:
        with self._lock:
            customized_row = self._connection.execute(
                "SELECT value FROM stats_meta WHERE key='settings_layout_customized'"
            ).fetchone()
            rows = self._connection.execute(
                "SELECT layout_key, position, description FROM settings_layout ORDER BY position, layout_key"
            )
            entries = [dict(row) for row in rows]
        return {
            "customized": bool(customized_row and customized_row["value"] == "1"),
            "entries": entries,
        }

    def save_settings_layout(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM settings_layout")
            self._connection.executemany(
                "INSERT INTO settings_layout(layout_key, position, description) VALUES (?, ?, ?)",
                [
                    (str(item["layout_key"]), int(item["position"]), str(item.get("description", "")))
                    for item in entries
                ],
            )
            self._connection.execute(
                "INSERT INTO stats_meta(key, value) VALUES ('settings_layout_customized', '1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
        return self.settings_layout()

    def reset_settings_layout(self) -> dict[str, Any]:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM settings_layout")
            self._connection.execute(
                "INSERT INTO stats_meta(key, value) VALUES ('settings_layout_customized', '0') "
                "ON CONFLICT(key) DO UPDATE SET value='0'"
            )
        return self.settings_layout()

    def observe(self, state: dict[str, Any]) -> None:
        current_tool = int(state.get("current_tool", -2))
        sensor_error = bool(state.get("sensor_error", current_tool == -2))
        print_state = str(state.get("print_state", "unknown"))
        observed = (current_tool, sensor_error, print_state)
        with self._lock:
            previous = self._last_state
            self._last_state = observed
        if previous is None:
            return
        old_tool, old_error, _old_print_state = previous
        if print_state != "printing":
            return
        if sensor_error and not old_error:
            self.record(
                "toolchange_failed",
                tool=old_tool if old_tool >= 0 else None,
                success=False,
                details={"previous_tool": old_tool},
            )
        if current_tool == old_tool:
            return
        if old_tool >= 0:
            self.record("tool_park", tool=old_tool, details={"next_tool": current_tool})
        if current_tool >= 0:
            self.record("tool_pickup", tool=current_tool, details={"previous_tool": old_tool})

    def reset_toolchange_stats(self) -> dict[str, Any]:
        started_at = time.time()
        placeholders = ",".join("?" for _ in TOOLCHANGE_EVENTS)
        with self._lock, self._connection:
            self._connection.execute(f"DELETE FROM events WHERE event_type IN ({placeholders})", TOOLCHANGE_EVENTS)
            self._connection.execute(
                "INSERT INTO stats_meta(key, value) VALUES ('started_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(started_at),),
            )
            self._last_state = None
        return {"ok": True, "started_at": started_at}

    def summary(self, recent_limit: int = 24) -> dict[str, Any]:
        placeholders = ",".join("?" for _ in TOOLCHANGE_EVENTS)
        with self._lock:
            totals = {name: 0 for name in TOOLCHANGE_EVENTS}
            totals.update({
                row["event_type"]: row["count"]
                for row in self._connection.execute(
                    f"SELECT event_type, COUNT(*) AS count FROM events WHERE event_type IN ({placeholders}) GROUP BY event_type",
                    TOOLCHANGE_EVENTS,
                )
            })
            per_tool = [dict(row) for row in self._connection.execute(
                f"""
                SELECT tool,
                       SUM(CASE WHEN event_type = 'tool_pickup' THEN 1 ELSE 0 END) AS pickups,
                       SUM(CASE WHEN event_type = 'tool_park' THEN 1 ELSE 0 END) AS parks,
                       SUM(CASE WHEN event_type = 'toolchange_failed' THEN 1 ELSE 0 END) AS errors
                FROM events
                WHERE tool IS NOT NULL AND event_type IN ({placeholders})
                GROUP BY tool ORDER BY tool
                """,
                TOOLCHANGE_EVENTS,
            )]
            rows = self._connection.execute(
                f"SELECT id, created_at, event_type, tool, success, details FROM events WHERE event_type IN ({placeholders}) ORDER BY created_at DESC LIMIT ?",
                (*TOOLCHANGE_EVENTS, recent_limit),
            )
            recent = []
            for row in rows:
                item = dict(row)
                item["success"] = bool(item["success"])
                try:
                    item["details"] = json.loads(item["details"])
                except json.JSONDecodeError:
                    item["details"] = {}
                recent.append(item)
            meta = self._connection.execute("SELECT value FROM stats_meta WHERE key='started_at'").fetchone()
            started_at = float(meta["value"]) if meta else time.time()
        return {"totals": totals, "per_tool": per_tool, "recent": recent, "started_at": started_at}
