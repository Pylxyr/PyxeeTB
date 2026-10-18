from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.customcommands import MAX_RESPONSE_LENGTH, clean_name
from pyxeetb.textutil import parse_uint
from pyxeetb.tunables import TUNABLE_BOUNDS

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.counters import CounterStore
    from pyxeetb.customcommands import CustomCommandStore

log = logging.getLogger(__name__)

_MAX_COOLDOWN = TUNABLE_BOUNDS["custom_command_cooldown_seconds"][1]


class CustomCommandsComponent(commands.Component):
    """Broadcaster-only chat commands: creating, editing and deleting them.
    Moderators are refused by the guard (silently — GuardFailure is quiet in
    chatbot.py). Running them is handled by the bot's CommandNotFound hook
    (see chatbot.py) via `CustomCommandStore.execute`, which is owner-only too."""

    def __init__(self, reply: Reply, custom: CustomCommandStore, counters: CounterStore, reserved_names: frozenset[str]) -> None:
        self._reply = reply
        self._custom = custom
        self._counters = counters
        self._reserved_names = reserved_names

    @commands.is_broadcaster()
    @commands.command(name="addcom", aliases=["editcom"])
    async def add_command_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        parts = args.strip().split(maxsplit=1)
        if len(parts) != 2:
            await self._reply(ctx, "Usage: !addcom <name> <response>  (variables: {user} {touser} {args} {count} {channel})")
            return
        name, response = clean_name(parts[0]), parts[1].strip()
        if name is None:
            await self._reply(ctx, "Command names can use letters, numbers and _ (max 25 characters).")
            return
        if name in self._reserved_names or self._counters.get(name) is not None:
            await self._reply(ctx, f"!{name} is already a command — pick a different name.")
            return
        if len(response) > MAX_RESPONSE_LENGTH:
            await self._reply(ctx, f"Keep responses under {MAX_RESPONSE_LENGTH} characters.")
            return
        await self._custom.save(name, response, str(ctx.chatter.id))
        log.info("Custom command !%s set by %s (%s)", name, ctx.chatter.display_name, ctx.chatter.id)
        await self._reply(ctx, f"Saved !{name}.")

    @commands.is_broadcaster()
    @commands.command(name="delcom")
    async def del_command_cmd(self, ctx: commands.Context, *, name: str = "") -> None:
        cleaned = clean_name(name)
        removed = cleaned is not None and await self._custom.delete(cleaned)
        await self._reply(ctx, f"Removed !{cleaned}." if removed else f"No custom command !{cleaned or name.strip()}.")

    @commands.is_broadcaster()
    @commands.command(name="comopt")
    async def command_options_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        """!comopt <name> cd <seconds|default>"""
        usage = "Usage: !comopt <name> cd <seconds|default>"
        parts = args.split()
        name = clean_name(parts[0]) if parts else None
        if name is None or len(parts) != 3 or parts[1].lower() not in ("cd", "cooldown"):
            await self._reply(ctx, usage)
            return
        value = parts[2].lower()
        if value == "default":
            seconds = -1
        elif (parsed := parse_uint(value)) is not None and parsed <= _MAX_COOLDOWN:
            seconds = parsed
        else:
            await self._reply(ctx, f"Cooldown must be 0-{_MAX_COOLDOWN} seconds, or 'default'.")
            return
        found = await self._custom.set_option(name, cooldown_seconds=seconds)
        label = "the default cooldown" if seconds < 0 else f"a {seconds}s cooldown"
        await self._reply(ctx, f"!{name} now uses {label}." if found else f"No custom command !{name}.")
