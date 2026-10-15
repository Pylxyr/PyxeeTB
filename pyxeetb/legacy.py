"""One-time import of the pre-PyxeeTB state files.

Older installs kept tunables, feature toggles and the PC specs/peripherals in three
JSON files under data/. Settings now live in the database (so backups include them)
and `!specs` / `!peripherals` are ordinary custom commands. On the first start after
upgrading, anything found is imported and each file renamed to `<name>.migrated` so
it is never imported twice. Safe to run on every start: with no files, it does nothing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pyxeetb.db import Database
from pyxeetb.settings import LiveSettings
from pyxeetb.toggles import FeatureToggles
from pyxeetb.tunables import TwitchTunables

log = logging.getLogger(__name__)

_PC_FIELDS = (
    ("cpu", "CPU"), ("cooler", "Cooler"), ("gpu", "GPU"), ("ram", "RAM"),
    ("motherboard", "Motherboard"), ("psu", "PSU"), ("case", "Case"),
)
_PERIPHERAL_FIELDS = (
    ("mouse", "Mouse"), ("monitor", "Monitor"), ("keyboard", "Keyboard"),
    ("iem_headset", "IEM/Headset"), ("controller", "Controller"),
)
_MAX_FIELD = 40


def _read(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _line(data: dict[str, Any], fields: tuple[tuple[str, str], ...]) -> str:
    parts = []
    for key, label in fields:
        raw = data.get(key, "")
        value = " ".join(raw.split())[:_MAX_FIELD] if isinstance(raw, str) else ""
        if value:
            parts.append(f"{label}: {value.replace('{', '(').replace('}', ')')}")
    return " | ".join(parts)


def _retire(path: Path) -> None:
    try:
        path.rename(path.with_name(path.name + ".migrated"))
    except OSError:
        log.warning("Couldn't rename %s after importing it.", path)


async def import_legacy_state(db: Database, settings: LiveSettings, data_dir: Path) -> list[str]:
    """Returns a human-readable list of what was imported (empty when nothing was)."""
    done: list[str] = []

    tunables_file = data_dir / "tunables.json"
    if (data := _read(tunables_file)) is not None:
        await settings.replace(tunables=TwitchTunables.from_dict(data))
        _retire(tunables_file)
        done.append("tunables")

    toggles_file = data_dir / "toggles.json"
    if (data := _read(toggles_file)) is not None:
        await settings.replace(toggles=FeatureToggles.from_dict(data))
        _retire(toggles_file)
        done.append("feature toggles")

    specs_file = data_dir / "specs.json"
    if (data := _read(specs_file)) is not None:
        existing = {c.name for c in await db.load_commands()}
        for name, fields in (("specs", _PC_FIELDS), ("peripherals", _PERIPHERAL_FIELDS)):
            text = _line(data, fields)
            if text and name not in existing:
                await db.set_command(name, text[:400], "import")
                done.append(f"!{name} (now a custom command)")
        _retire(specs_file)

    if done:
        log.info("Imported from the old state files: %s.", ", ".join(done))
    return done
