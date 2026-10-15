from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.counters import MAX_COUNTERS_LISTED
from pyxeetb.customcommands import clean_name
from pyxeetb.textutil import parse_int

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.counters import CounterStore
    from pyxeetb.customcommands import CustomCommandStore

log = logging.getLogger(__name__)

_USAGE = (
    "Usage: !counter add|del|set|public <name> [value] | list — "
    "view/adjust any counter with !<name> / !<name>++ / !<name>--"
)


class CountersComponent(commands.Component):
    """Management for named counters (!deaths, !wins, ...) — reading and
    incrementing them (!<name>, !<name>++/--) goes through the same
    CommandNotFound fallback path as custom commands; see chatbot.py's
    event_command_error and _try_counter_command."""

    def __init__(self, reply: Reply, counters: CounterStore, custom: CustomCommandStore, reserved_names: frozenset[str]) -> None:
        self._reply = reply
        self._counters = counters
        self._custom = custom
        self._reserved_names = reserved_names

    @commands.is_moderator()
    @commands.command(name="counter")
    async def counter_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        parts = args.strip().split(maxsplit=2)
        if parts and parts[0].lower() == "list":
            names = [c.name for c in self._counters.all()[:MAX_COUNTERS_LISTED]]
            total = len(self._counters.all())
            more = f" (+{total - len(names)} more)" if total > len(names) else ""
            await self._reply(ctx, f"Counters: {', '.join(names)}{more}" if names else "No counters yet.")
            return
        if len(parts) < 2:
            await self._reply(ctx, _USAGE)
            return
        action, name = parts[0].lower(), clean_name(parts[1])
        value_text = parts[2] if len(parts) > 2 else ""
        if name is None:
            await self._reply(ctx, "Counter names can use letters, numbers and _ (max 25 characters).")
            return
        counters = self._counters
        if action == "add":
            if name in self._reserved_names or self._custom.get(name) is not None:
                await self._reply(ctx, f"!{name} is already a command — pick a different name.")
                return
            created = await counters.create(name, str(ctx.chatter.id))
            await self._reply(ctx, f"Counter !{name} created, starting at 0." if created else f"!{name} already exists.")
        elif action in ("del", "delete", "remove"):
            removed = await counters.delete(name)
            await self._reply(ctx, f"Removed counter !{name}." if removed else f"No counter named {name}.")
        elif action == "set":
            new_value = parse_int(value_text)
            if new_value is None:
                await self._reply(ctx, "Usage: !counter set <name> <value>")
                return
            found = await counters.set_value(name, new_value)
            await self._reply(ctx, f"!{name} set to {new_value}." if found else f"No counter named {name}.")
        elif action == "public":
            on = value_text.strip().lower() != "off"
            found = await counters.set_public(name, on)
            state = "anyone" if on else "moderators only"
            await self._reply(ctx, f"!{name} can now be incremented by {state}." if found else f"No counter named {name}.")
        else:
            await self._reply(ctx, _USAGE)
