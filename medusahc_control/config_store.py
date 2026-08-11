from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .settings import inspect_variable_config


class ConfigStore:
    """Safely writes validated MedusaHC macro values to their source config."""

    def __init__(self, variables_config: str, backup_dir: str | Path):
        self.variables_config = Path(variables_config).expanduser().resolve()
        self.backup_dir = Path(backup_dir).expanduser().resolve()
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self.variables_config.is_file()

    def inspect_variables(self) -> dict[tuple[str, str], dict[str, Any]]:
        with self._lock:
            if not self.available:
                raise ValueError(f"MedusaHC variables file was not found: {self.variables_config}")
            return inspect_variable_config(self.variables_config.read_text(encoding="utf-8"))

    def save_permanent(self, definition: dict[str, Any], value: float | int) -> None:
        with self._lock:
            if not self.available:
                raise ValueError("MedusaHC variables configuration is not available")
            original = self.variables_config.read_text(encoding="utf-8")
            updated = self._replace_macro_variable(
                original,
                str(definition["macro"]),
                str(definition["variable"]),
                value,
            )
            self._backup(self.variables_config)
            self._atomic_write(self.variables_config, updated)

    @staticmethod
    def _replace_macro_variable(text: str, macro: str, variable: str, value: float | int) -> str:
        section_pattern = re.compile(
            rf"(?ms)^\[gcode_macro\s+{re.escape(macro)}\]\s*.*?(?=^\[|\Z)"
        )
        section_match = section_pattern.search(text)
        if not section_match:
            raise ValueError(f"Macro section [gcode_macro {macro}] was not found")
        section = section_match.group(0)
        variable_pattern = re.compile(
            rf"(?m)^(\s*variable_{re.escape(variable)}\s*:\s*)([^#\r\n]*?)(\s*(?:#.*)?)$"
        )
        if not variable_pattern.search(section):
            raise ValueError(f"variable_{variable} was not found in [gcode_macro {macro}]")
        number = str(int(value)) if isinstance(value, int) or float(value).is_integer() else f"{float(value):g}"
        updated_section = variable_pattern.sub(rf"\g<1>{number}\g<3>", section, count=1)
        return text[: section_match.start()] + updated_section + text[section_match.end() :]

    def _backup(self, path: Path) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = self.backup_dir / f"{path.name}.{stamp}.{time.time_ns()}.bak"
        shutil.copy2(path, target)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, mode)
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
