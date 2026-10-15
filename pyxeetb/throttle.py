"""Command throttling and usage counting.

Every built-in command reply is a chat message (and some are API calls), so one
chatter spamming `!points` — or a crowd all typing the same command — must not
turn into bot traffic. Throttled invocations are silent: replying to spam is also
traffic. Moderators and the broadcaster are exempt.

The same hook counts how often each command is actually used, so deciding whether
a command earns its keep is a matter of looking at the numbers (shown on /settings).
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable

from pyxeetb.cooldown import CooldownTracker
from pyxeetb.db import Database

log = logging.getLogger(__name__)

DEFAULT_USER_SECONDS = 5.0
DEFAULT_GLOBAL_SECONDS = 2.0
# Commands that cost a Twitch API call each get a longer leash (!clip keeps its own
# cooldown, which only starts once a clip was actually made).
OVERRIDES: dict[str, tuple[float, float]] = {
    "followage": (15.0, 3.0),
}


class CommandThrottle:
    def __init__(
        self,
        overrides: dict[str, tuple[float, float]] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._overrides = OVERRIDES if overrides is None else overrides
        self._cooldowns = CooldownTracker(clock)

    def allow(self, command: str, user_id: str, *, exempt: bool = False) -> bool:
        """True if the command may run now (and records the use); False if this
        chatter, or the channel as a whole, used it too recently."""
        if exempt:
            return True
        user_seconds, global_seconds = self._overrides.get(command, (DEFAULT_USER_SECONDS, DEFAULT_GLOBAL_SECONDS))
        user_key, global_key = f"{command}:{user_id}", f"{command}:*"
        if (
            self._cooldowns.remaining(user_key, user_seconds) > 0
            or self._cooldowns.remaining(global_key, global_seconds) > 0
        ):
            return False
        self._cooldowns.mark(user_key)
        self._cooldowns.mark(global_key)
        return True


class UsageCounter:
    """Counts command uses in memory and writes them to the database in batches."""

    def __init__(self) -> None:
        self._pending: Counter[str] = Counter()

    def record(self, command: str) -> None:
        self._pending[command] += 1

    async def flush(self, db: Database) -> None:
        if not self._pending:
            return
        batch, self._pending = dict(self._pending), Counter()
        try:
            await db.add_command_usage(batch)
        except Exception:
            self._pending.update(batch)  # keep the counts for the next flush
            log.warning("Couldn't save command usage counts (will retry).", exc_info=True)
