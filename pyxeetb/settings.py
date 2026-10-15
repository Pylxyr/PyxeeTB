"""Runtime-adjustable settings, kept in SQLite next to everything else.

Only values that differ from the code's defaults are stored (absent = default), so a
default changed in a later release reaches every install that never customised that
knob, and a backup of community.db carries the settings with it.

`LiveSettings` holds the current values in memory: reading them is a plain
attribute access (no await, no file stat, no parsing per chat message), and every
change goes through one method that writes to the database first.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pyxeetb.db import Database
from pyxeetb.toggles import FeatureToggles
from pyxeetb.tunables import TwitchTunables

log = logging.getLogger(__name__)

_TUNABLE = "tunable."
_TOGGLE = "toggle."


class LiveSettings:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._overrides: dict[str, str] = {}
        self._tunables = TwitchTunables()
        self._toggles = FeatureToggles()

    # -- reading (synchronous, in memory) -----------------------------------

    @property
    def tunables(self) -> TwitchTunables:
        return self._tunables

    @property
    def toggles(self) -> FeatureToggles:
        return self._toggles

    # -- loading / changing --------------------------------------------------

    async def load(self) -> None:
        self._overrides = await self._db.load_settings()
        self._rebuild()

    def _rebuild(self) -> None:
        tunables: dict[str, Any] = {}
        toggles: dict[str, Any] = {}
        for key, raw in self._overrides.items():
            try:
                value = json.loads(raw)
            except ValueError:
                log.warning("Ignoring unreadable setting %r.", key)
                continue
            if key.startswith(_TUNABLE):
                tunables[key[len(_TUNABLE):]] = value
            elif key.startswith(_TOGGLE):
                toggles[key[len(_TOGGLE):]] = value
        self._tunables = TwitchTunables.from_dict(tunables)
        self._toggles = FeatureToggles.from_dict(toggles)

    async def replace(
        self,
        *,
        tunables: TwitchTunables | None = None,
        toggles: FeatureToggles | None = None,
    ) -> None:
        """Makes the given groups current (a group left as None is untouched) and
        stores only their non-default values, in one transaction."""
        sets: dict[str, str] = {}
        wanted: set[str] = set()
        if tunables is not None:
            for name, value in tunables.to_overrides().items():
                sets[_TUNABLE + name] = json.dumps(value)
            wanted |= {k for k in sets if k.startswith(_TUNABLE)}
        if toggles is not None:
            for name, value in toggles.to_overrides().items():
                sets[_TOGGLE + name] = json.dumps(value)
            wanted |= {k for k in sets if k.startswith(_TOGGLE)}
        prefixes = tuple(p for p, group in ((_TUNABLE, tunables), (_TOGGLE, toggles)) if group is not None)
        deletes = [k for k in self._overrides if k.startswith(prefixes) and k not in wanted]
        await self._db.write_settings(sets, deletes)
        self._overrides = {k: v for k, v in self._overrides.items() if k not in deletes}
        self._overrides.update(sets)
        self._rebuild()

    async def update(self, **values: int | bool) -> None:
        """Sets any mix of tunables and toggles by name, in one transaction."""
        tunables = TwitchTunables.from_dict(self._tunables.to_dict())
        toggles = FeatureToggles.from_dict(self._toggles.to_dict())
        for key, value in values.items():
            if hasattr(tunables, key):
                setattr(tunables, key, value)
            elif hasattr(toggles, key):
                setattr(toggles, key, value)
            else:
                raise KeyError(key)
        await self.replace(tunables=tunables, toggles=toggles)

    async def set_tunable(self, key: str, value: int) -> None:
        tunables = TwitchTunables.from_dict(self._tunables.to_dict())
        setattr(tunables, key, value)
        await self.replace(tunables=tunables)

    async def set_toggle(self, key: str, value: bool) -> None:
        toggles = FeatureToggles.from_dict(self._toggles.to_dict())
        setattr(toggles, key, value)
        await self.replace(toggles=toggles)
