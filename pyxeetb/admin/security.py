"""Security helpers for the admin server that need nothing but the stdlib.

Everything here is a plain function or class with no aiohttp dependency, so
the rules that actually protect /settings live in one small module that can
be read (and reasoned about) on its own instead of being spread through the
request handlers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def origin_matches_host(origin: str | None, referer: str | None, hosts: tuple[str | None, ...]) -> bool:
    """Origin (or Referer) must name one of `hosts`. Requests carrying neither
    header (curl, scripts) pass; browsers always send Origin on cross-site POSTs."""
    source = origin
    if source is None and referer:
        try:
            parts = urlsplit(referer)
        except ValueError:
            return False
        source = f"{parts.scheme}://{parts.netloc}"
    if source is None:
        return True
    allowed: set[str] = set()
    for host in hosts:
        host = (host or "").strip().lower()
        if host:
            allowed.update((f"http://{host}", f"https://{host}"))
    return source.lower() in allowed


def fetch_site_ok(sec_fetch_site: str | None) -> bool:
    if sec_fetch_site is None:
        return True
    return sec_fetch_site.strip().lower() in ("same-origin", "none")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class _SlidingWindow:
    """Per-key event timestamps within a trailing window, bounded in memory.

    Keys whose events have all expired are dropped rather than kept forever
    (the old limiters only pruned a key when that same key came back, so every
    one-off client left an entry behind for the life of the process), and the
    number of tracked keys is capped so a flood of distinct source addresses
    can't grow it without limit.
    """

    def __init__(
        self,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 4096,
    ) -> None:
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._events: dict[str, list[float]] = {}

    def _live(self, key: str, now: float) -> list[float]:
        events = [t for t in self._events.get(key, ()) if now - t < self._window]
        if events:
            self._events[key] = events
        else:
            self._events.pop(key, None)
        return events

    def count(self, key: str) -> int:
        return len(self._live(key, self._clock()))

    def add(self, key: str) -> None:
        now = self._clock()
        events = self._live(key, now)
        events.append(now)
        self._events[key] = events
        if len(self._events) > self._max_keys:
            self._shrink(now)

    def clear(self, key: str) -> None:
        self._events.pop(key, None)

    def seconds_until_below(self, key: str, limit: int) -> float:
        now = self._clock()
        events = self._live(key, now)
        if len(events) < limit:
            return 0.0
        return max(0.0, events[len(events) - limit] + self._window - now)

    def _shrink(self, now: float) -> None:
        for key in list(self._events):
            self._live(key, now)
        # Still over the cap with every remaining key live: drop the
        # longest-tracked ones (dict order is insertion order).
        excess = len(self._events) - (self._max_keys * 3) // 4
        if excess > 0:
            for key in list(self._events)[:excess]:
                del self._events[key]

    def __len__(self) -> int:
        return len(self._events)


class RequestRateLimiter:
    """Plain per-key throttle with no lockout escalation, for public routes
    where there's no secret to brute-force and the goal is just to stop one
    client turning a cheap page into load on the rest of the process.
    allow() says yes or no for *this* request."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_requests
        self._hits = _SlidingWindow(window_seconds, clock=clock)

    def allow(self, key: str) -> bool:
        if self._hits.count(key) >= self._max:
            return False
        self._hits.add(key)
        return True


class ConnectionLimiter:
    """Caps simultaneous long-lived connections (the chat WebSocket) per client
    and in total, so a script can't hold open thousands of sockets. acquire()
    says whether this one may open; release() must follow in a `finally`."""

    def __init__(self, max_per_key: int, max_total: int) -> None:
        self._max_per_key = max_per_key
        self._max_total = max_total
        self._open: dict[str, int] = {}
        self._total = 0

    def acquire(self, key: str) -> bool:
        if self._total >= self._max_total or self._open.get(key, 0) >= self._max_per_key:
            return False
        self._open[key] = self._open.get(key, 0) + 1
        self._total += 1
        return True

    def release(self, key: str) -> None:
        count = self._open.get(key, 0)
        if count <= 0:
            return
        self._total -= 1
        if count == 1:
            del self._open[key]
        else:
            self._open[key] = count - 1

    @property
    def total(self) -> int:
        return self._total
