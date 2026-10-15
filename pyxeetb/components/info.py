from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.commands_reference import COMMANDS

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.counters import CounterStore
    from pyxeetb.customcommands import CustomCommandStore


class InfoComponent(commands.Component):
    def __init__(self, reply: Reply, prefix: str, public_commands_url: str | None, custom: CustomCommandStore, counters: CounterStore) -> None:
        self._reply = reply
        self._prefix = prefix
        self._public_commands_url = public_commands_url
        self._custom = custom
        self._counters = counters

    @commands.command(name="commands", aliases=["help"])
    async def commands_list(self, ctx: commands.Context) -> None:
        """Links to the public /commands page when TWITCH_PUBLIC_BASE_URL is
        set — a categorized, searchable reference any chatter can open, not
        just mods with the /settings password. Otherwise falls back to a
        terse in-chat listing built from the same commands_reference.COMMANDS,
        so a command that shouldn't show here (public=False) just needs
        that one flag set in one place."""
        if self._public_commands_url:
            await self._reply(
                ctx, f"Full list of commands, what they do, and how to use them: {self._public_commands_url}"
            )
            return
        p = self._prefix
        anyone = [c for c in COMMANDS if c.public and c.group == "anyone"]
        mods = [c for c in COMMANDS if c.public and c.group == "moderators"]
        parts = [" | ".join(f"{p}{c.name}" for c in anyone), "mods: " + ", ".join(f"{p}{c.name}" for c in mods)]
        custom = self._custom.all()
        if custom:
            parts.append("custom: " + ", ".join(f"{p}{c.name}" for c in custom))
        counters = self._counters.all()
        if counters:
            parts.append("counters: " + ", ".join(f"{p}{c.name}" for c in counters))
        await self._reply(ctx, "  |  ".join(parts))
