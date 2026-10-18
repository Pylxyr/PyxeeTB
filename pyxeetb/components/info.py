from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.commands_reference import COMMANDS

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.counters import CounterStore


class InfoComponent(commands.Component):
    def __init__(self, reply: Reply, prefix: str, public_commands_url: str | None, counters: CounterStore) -> None:
        self._reply = reply
        self._prefix = prefix
        self._public_commands_url = public_commands_url
        self._counters = counters

    @commands.command(name="commands", aliases=["help"])
    async def commands_list(self, ctx: commands.Context) -> None:
        """Links to the public commands page (GitHub Pages by default; see
        config.DEFAULT_PUBLIC_COMMANDS_URL) — a categorized, searchable
        reference any chatter can open. Falls back to a terse in-chat listing
        built from the same commands_reference.COMMANDS only when the link is
        deliberately blanked, so a command that shouldn't show here
        (public=False) needs that one flag set in one place. Custom commands
        are owner-only and never listed here."""
        if self._public_commands_url:
            await self._reply(
                ctx, f"Full list of commands, what they do, and how to use them: {self._public_commands_url}"
            )
            return
        p = self._prefix
        anyone = [c for c in COMMANDS if c.public and c.group == "anyone"]
        mods = [c for c in COMMANDS if c.public and c.group == "moderators"]
        parts = [" | ".join(f"{p}{c.name}" for c in anyone), "mods: " + ", ".join(f"{p}{c.name}" for c in mods)]
        counters = self._counters.all()
        if counters:
            parts.append("counters: " + ", ".join(f"{p}{c.name}" for c in counters))
        await self._reply(ctx, "  |  ".join(parts))
