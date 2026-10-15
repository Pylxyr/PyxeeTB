from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.customcommands import clean_name
from pyxeetb.textutil import parse_uint
from pyxeetb.timers import MAX_MIN_MESSAGES, TimerScheduler, parse_add

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pyxeetb.actions import Announce, Reply
    from pyxeetb.db import Database
    from pyxeetb.settings import LiveSettings

log = logging.getLogger(__name__)

_TICK_SECONDS = 30
_USAGE = "Usage: !timer add <name> <minutes> <message> | remove <name> | on|off <name> | min <name> <messages> | list"


class TimersComponent(commands.Component):
    def __init__(self, reply: Reply, announce: Announce, db: Database, settings: LiveSettings, chat_messages: Callable[[], int], is_live: Callable[[], Awaitable[bool]]) -> None:
        self._reply = reply
        self._announce = announce
        self._db = db
        self._settings = settings
        self._chat_messages = chat_messages
        self._is_live = is_live
        self._scheduler = TimerScheduler()
        self._task: asyncio.Task[None] | None = None

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="timers")

    async def component_teardown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(_TICK_SECONDS)
            try:
                await self.tick()
            except Exception:
                log.exception("Timer tick failed (non-fatal).")

    async def tick(self) -> int:
        """One scheduler pass; returns how many timers were posted."""
        toggles = self._settings.toggles
        if not toggles.timers_enabled or not await self._is_live():
            self._scheduler.reset()
            return 0
        due = self._scheduler.due(
            await self._db.list_timers(), now=time.monotonic(), total_messages=self._chat_messages()
        )
        for timer in due:
            await self._announce(timer.message)
        return len(due)

    @commands.is_moderator()
    @commands.command(name="timer")
    async def timer_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        sub, _, rest = args.strip().partition(" ")
        sub, rest = sub.lower(), rest.strip()
        db = self._db
        if sub == "add":
            parsed = parse_add(rest)
            if isinstance(parsed, str):
                await self._reply(ctx, parsed)
                return
            name, minutes, message = parsed
            await db.set_timer(name, message, minutes, str(ctx.chatter.id))
            await self._reply(ctx, f"Timer {name} saved: every {minutes} min while live (needs some chat activity).")
        elif sub in ("remove", "delete", "del"):
            target = clean_name(rest)
            removed = target is not None and await db.delete_timer(target)
            await self._reply(ctx, f"Removed timer {target}." if removed else f"No timer named {rest or '?'}.")
        elif sub in ("on", "off"):
            target = clean_name(rest)
            found = target is not None and await db.set_timer_enabled(target, sub == "on")
            await self._reply(ctx, f"Timer {target} is {sub}." if found else f"No timer named {rest or '?'}.")
        elif sub == "min":
            name_text, _, count_text = rest.partition(" ")
            target = clean_name(name_text)
            min_messages = parse_uint(count_text)
            if target is None or min_messages is None or min_messages > MAX_MIN_MESSAGES:
                await self._reply(ctx, f"Usage: !timer min <name> <0-{MAX_MIN_MESSAGES}>")
                return
            found = await db.set_timer_min_messages(target, min_messages)
            await self._reply(ctx, f"Timer {target} needs {min_messages} chat messages." if found else f"No timer named {target}.")
        elif sub == "list":
            timers = await db.list_timers()
            if not timers:
                await self._reply(ctx, "No timers yet.")
                return
            listing = ", ".join(f"{t.name} ({t.interval_minutes}m{'' if t.enabled else ', off'})" for t in timers)
            await self._reply(ctx, f"Timers: {listing}")
        else:
            await self._reply(ctx, _USAGE)
