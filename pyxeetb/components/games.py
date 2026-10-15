from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.chatevent import display_name_of
from pyxeetb.textutil import parse_uint

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.automod import AutoMod
    from pyxeetb.db import Database
    from pyxeetb.duels import DuelManager
    from pyxeetb.settings import LiveSettings


class GamesComponent(commands.Component):
    """!duel and its !accept/!decline — a PvP variant of !gamble (see
    components/economy.py), backed by pyxeetb.duels.DuelManager."""

    def __init__(self, reply: Reply, duels: DuelManager, db: Database, settings: LiveSettings, automod: AutoMod) -> None:
        self._reply = reply
        self._duels = duels
        self._db = db
        self._settings = settings
        self._automod = automod

    @commands.command(name="duel")
    async def duel_cmd(self, ctx: commands.Context, target: str = "", amount: str = "") -> None:
        if not self._settings.toggles.duels_enabled:
            await self._reply(ctx, "Duels are turned off.")
            return
        target = target.strip().lstrip("@")
        bet = parse_uint(amount)
        if not target or bet is None or bet < 1:
            await self._reply(ctx, "Usage: !duel <user> <amount>")
            return
        tunables = self._settings.tunables
        if not tunables.duel_min_bet <= bet <= tunables.duel_max_bet:
            await self._reply(ctx, f"Duel bets must be between {tunables.duel_min_bet} and {tunables.duel_max_bet}.")
            return
        challenger_id = str(ctx.chatter.id)
        challenger_name = display_name_of(ctx.chatter)
        found = await self._db.find_by_name(target)
        if found is None:
            await self._reply(ctx, f"I haven't seen {self._automod.scrub(target, 32)} in chat yet.")
            return
        target_id, target_name = found
        stats = await self._db.get_stats(challenger_id)
        if (stats["points"] if stats else 0) < bet:
            await self._reply(ctx, f"You don't have {bet} points.")
            return
        error = self._duels.challenge(
            challenger_id, challenger_name, target_id, bet, timeout_seconds=tunables.duel_timeout_seconds
        )
        if error:
            await self._reply(ctx, error)
            return
        await self._reply(
            ctx,
            f"@{target_name}, {challenger_name} challenges you to a duel for {bet} points! "
            f"Type !accept or !decline within {tunables.duel_timeout_seconds}s.",
        )

    @commands.command(name="accept")
    async def accept_cmd(self, ctx: commands.Context) -> None:
        tunables = self._settings.tunables
        result = await self._duels.accept(
            str(ctx.chatter.id), display_name_of(ctx.chatter), tunables.duel_challenger_win_chance_percent
        )
        if isinstance(result, str):
            await self._reply(ctx, result)
            return
        winner_name, amount = result
        await self._reply(ctx, f"\u2694\ufe0f {winner_name} wins the duel and takes {amount} points!")

    @commands.command(name="decline")
    async def decline_cmd(self, ctx: commands.Context) -> None:
        challenge = self._duels.decline(str(ctx.chatter.id))
        if challenge is None:
            await self._reply(ctx, "You don't have a pending duel challenge.")
            return
        await self._reply(ctx, f"@{challenge.challenger_name}, {display_name_of(ctx.chatter)} declined the duel.")
