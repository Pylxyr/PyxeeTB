from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.chatevent import display_name_of

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.giveaway import GiveawayManager

_USAGE = "Usage: !giveaway — mods: start <prize...>|pick|reroll|cancel|status"


class GiveawayComponent(commands.Component):
    """A prize giveaway (!giveaway) — see pyxeetb.giveaway.GiveawayManager.
    Bare !giveaway both checks status and enters, matching the "type
    !giveaway to enter" convention most streams already use."""

    def __init__(self, reply: Reply, giveaway: GiveawayManager) -> None:
        self._reply = reply
        self._giveaway = giveaway

    @commands.command(name="giveaway")
    async def giveaway_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        manager = self._giveaway
        is_mod = bool(getattr(ctx.chatter, "moderator", False))
        first, _, rest = args.strip().partition(" ")
        sub = first.lower()

        if is_mod and sub == "start":
            if not rest.strip():
                await self._reply(ctx, "Usage: !giveaway start <prize description>")
                return
            manager.start(rest.strip(), str(ctx.chatter.id))
            await self._reply(ctx, f"\U0001f381 Giveaway started: {rest.strip()}! Type !giveaway to enter.")
            return
        if is_mod and sub == "pick":
            current = manager.current
            if current is not None and current.winner is not None:
                await self._reply(ctx, f"{current.winner} was already picked — use !giveaway reroll for a new winner.")
                return
            winner = manager.pick()
            if winner is None:
                await self._reply(ctx, "No giveaway to pick from.")
                return
            await self._reply(ctx, f"\U0001f389 {winner} wins the giveaway!")
            return
        if is_mod and sub == "reroll":
            winner = manager.reroll()
            if winner is None:
                await self._reply(ctx, "Nothing to re-roll — pick a winner first, or nobody else entered.")
                return
            await self._reply(ctx, f"\U0001f389 New winner: {winner}!")
            return
        if is_mod and sub == "cancel":
            cancelled = manager.cancel()
            await self._reply(ctx, "Giveaway cancelled." if cancelled else "No giveaway running.")
            return
        if sub == "status":
            current = manager.current
            if current is None:
                await self._reply(ctx, "No giveaway running." if not is_mod else _USAGE)
                return
            state = f"won by {current.winner}" if current.winner else f"{len(current.entrants)} entered"
            await self._reply(ctx, f"Giveaway: {current.prize} ({state})")
            return

        # A moderator's unrecognised subcommand is a typo, not an entry.
        if is_mod and sub and sub != "enter":
            await self._reply(ctx, _USAGE)
            return

        # Bare !giveaway (or an unrecognised word from a non-mod): enter.
        chatter_id, name = str(ctx.chatter.id), display_name_of(ctx.chatter)
        if manager.current is None:
            await self._reply(ctx, "No giveaway running right now.")
        elif manager.current.winner is not None:
            await self._reply(ctx, f"That giveaway already ended — {manager.current.winner} won.")
        elif manager.has_entered(chatter_id):
            await self._reply(ctx, "You're already entered!")
        elif manager.enter(chatter_id, name):
            await self._reply(ctx, f"{name}, you're entered for {manager.current.prize}! Good luck.")
