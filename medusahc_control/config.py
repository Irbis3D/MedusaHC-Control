from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    bind: str = "0.0.0.0"
    port: int = 8090
    moonraker_url: str = "http://127.0.0.1:7125"
    moonraker_api_key: str = ""
    simulate: bool = True
    poll_interval: float = 0.75
    database_path: str = "data/medusahc-control.db"
    control_token: str = ""
    max_temperature: float = 290.0
    allow_commands: bool = False
    printer_config_path: str = ""
    medusahc_variables_path: str = ""

    @classmethod
    def from_file(cls, path: str | Path | None) -> "AppConfig":
        if path is None:
            return cls()
        config_path = Path(path).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        known = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"Unknown configuration keys: {', '.join(unknown)}")
        config = cls(**raw)
        database_path = Path(config.database_path).expanduser()
        if not database_path.is_absolute():
            database_path = config_path.parent / database_path
        return replace(config, database_path=str(database_path.resolve()))

    def with_overrides(
        self,
        *,
        bind: str | None = None,
        port: int | None = None,
        simulate: bool | None = None,
    ) -> "AppConfig":
        return replace(
            self,
            bind=self.bind if bind is None else bind,
            port=self.port if port is None else port,
            simulate=self.simulate if simulate is None else simulate,
        )
