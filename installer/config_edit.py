from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


BEGIN = "# >>> MEDUSAHC MAINSAIL UPDATE MANAGER >>>"
END = "# <<< MEDUSAHC MAINSAIL UPDATE MANAGER <<<"


@dataclass(frozen=True)
class MoonrakerPlan:
    original: str
    updated: str
    removed_standard_updater: str = ""

    @property
    def changed(self) -> bool:
        return self.original != self.updated

    def diff(self, filename: str = "moonraker.conf") -> str:
        return "".join(
            difflib.unified_diff(
                self.original.splitlines(keepends=True),
                self.updated.splitlines(keepends=True),
                fromfile=f"{filename}.before",
                tofile=f"{filename}.after",
            )
        )


def _remove_managed_block(text: str) -> str:
    starts = text.count(BEGIN)
    ends = text.count(END)
    if starts != ends or starts > 1:
        raise ValueError("MedusaHC Mainsail markers are missing or duplicated")
    if not starts:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN)}\n.*?\n{re.escape(END)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def _section_pattern(name: str) -> re.Pattern[str]:
    header = rf"^[ \t]*\[update_manager[ \t]+{re.escape(name)}\][ \t]*\r?$"
    return re.compile(rf"(?ms){header}\n.*?(?=^[ \t]*\[|\Z)")


def extract_section(text: str, name: str) -> str:
    matches = list(_section_pattern(name).finditer(text))
    if len(matches) > 1:
        raise ValueError(f"moonraker.conf contains multiple [update_manager {name}] sections")
    return matches[0].group(0).rstrip() + "\n" if matches else ""


def remove_section(text: str, name: str) -> tuple[str, str]:
    section = extract_section(text, name)
    if not section:
        return text, ""
    updated = _section_pattern(name).sub("", text, count=1)
    return updated.rstrip() + "\n", section


def updater_block(path: str, repository: str) -> str:
    return (
        f"{BEGIN}\n"
        "[update_manager medusahc-mainsail]\n"
        "type: web\n"
        "channel: stable\n"
        f"repo: {repository}\n"
        f"path: {path}\n"
        "info_tags:\n"
        "    desc=Experimental MedusaHC Mainsail interface\n"
        f"{END}\n"
    )


def plan_install(text: str, *, mode: str, path: str, repository: str) -> MoonrakerPlan:
    if mode not in {"replace", "parallel"}:
        raise ValueError("mode must be replace or parallel")
    updated = _remove_managed_block(text)
    removed = ""
    if mode == "replace":
        updated, removed = remove_section(updated, "mainsail")
    if extract_section(updated, "medusahc-mainsail"):
        raise ValueError("An unmanaged [update_manager medusahc-mainsail] section already exists")
    updated = updated.rstrip() + "\n\n" + updater_block(path, repository)
    return MoonrakerPlan(text, updated, removed)


def plan_remove(text: str, *, standard_updater: str = "") -> MoonrakerPlan:
    updated = _remove_managed_block(text).rstrip() + "\n"
    if standard_updater:
        if extract_section(updated, "mainsail"):
            raise ValueError("Cannot restore standard updater: a mainsail updater already exists")
        updated = updated.rstrip() + "\n\n" + standard_updater.strip() + "\n"
    return MoonrakerPlan(text, updated)
