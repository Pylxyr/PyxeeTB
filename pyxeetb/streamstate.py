"""What the bot knows about the stream — live or not, since when, title, category —
in one place.

EventSub keeps it current for free: stream.online / stream.offline say when the
stream starts and stops, and channel.update carries every title or category
change. Helix is only a fallback: a slow reconciliation poll when those events
are flowing, a quicker one when they are not (a missing subscription must never
make `!title` stale or the points loop think the stream is offline).
"""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyxeetb.runtime import RuntimeStatus

log = logging.getLogger(__name__)

LIVE_TTL_EVENTS = 900.0  # events flowing: just a safety net
LIVE_TTL_POLLING = 120.0
INFO_TTL_EVENTS = 3600.0
INFO_TTL_POLLING = 60.0


@dataclass(slots=True)
class Reading:
    """One Helix lookup: whether live, and what the channel looks like."""

    live: bool
    started_at: datetime.datetime | None
    title: str
    game: str


class StreamState:
    def __init__(
        self,
        status: RuntimeStatus,
        fetch: Callable[[], Awaitable[Reading]],
        *,
        on_live_start: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._status = status
        self._fetch = fetch
        self._on_live_start = on_live_start
        self._clock = clock
        self.started_at: datetime.datetime | None = None
        self.title: str | None = None
        self.game: str | None = None
        self._live_checked_at = 0.0
        self._info_checked_at = 0.0

    # -- fed by EventSub -----------------------------------------------------

    def set_live(self, live: bool, started_at: datetime.datetime | None = None) -> bool:
        """Records a live/offline reading; True if the state actually changed."""
        first = self._status.live.is_live is None
        flipped = self._status.live.update(live)
        self.started_at = started_at if live else None
        if live and (flipped or first):
            self._on_live_start()
        self._live_checked_at = self._clock()
        return flipped

    def apply_channel_update(self, title: str, game: str) -> None:
        self.title, self.game = title, game
        self._info_checked_at = self._clock()

    # -- reads ---------------------------------------------------------------

    def _events(self, *names: str) -> bool:
        return all(self._status.alert_subscriptions.get(n) for n in names)

    async def _refresh(self) -> bool:
        try:
            reading = await self._fetch()
        except Exception:
            log.warning("Stream lookup failed (non-fatal).", exc_info=True)
            return False
        self.set_live(reading.live, reading.started_at)
        self.apply_channel_update(reading.title, reading.game)
        return True

    async def is_live(self) -> bool:
        """Best-effort and cached. On a failed lookup the last known state is kept
        (assuming live if there is none) — silently zeroing everyone's earnings
        over one timed-out call is worse than over-awarding for a tick."""
        known = self._status.live.is_live
        ttl = LIVE_TTL_EVENTS if self._events("stream_online", "stream_offline") else LIVE_TTL_POLLING
        if known is not None and self._clock() - self._live_checked_at < ttl:
            return known
        if await self._refresh():
            return bool(self._status.live.is_live)
        return True if known is None else known

    async def uptime(self) -> datetime.timedelta | None:
        """How long the stream has been live; None when offline or unknown."""
        if not await self.is_live():
            return None
        if self.started_at is None:
            await self._refresh()
        if self.started_at is None:
            return None
        return datetime.datetime.now(datetime.timezone.utc) - self.started_at

    async def channel_info(self) -> tuple[str, str] | None:
        """(title, category), or None if it can't be determined."""
        ttl = INFO_TTL_EVENTS if self._events("channel_update") else INFO_TTL_POLLING
        stale = self.title is None or self._clock() - self._info_checked_at >= ttl
        if stale:
            await self._refresh()
        if self.title is None:
            return None
        return self.title, self.game or ""
