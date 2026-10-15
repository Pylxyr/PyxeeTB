from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.chatevent import display_name_of
from pyxeetb.economy import format_duration

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.automod import AutoMod
    from pyxeetb.db import Database
    from pyxeetb.economy import Economy


class EconomyComponent(commands.Component):
    """Thin chat layer over `Economy` — every rule lives in pyxeetb/economy.py."""

    def __init__(self, reply: Reply, economy: Economy, db: Database, automod: AutoMod) -> None:
        self._reply = reply
        self._economy = economy
        self._db = db
        self._automod = automod

    @commands.command(name="points", aliases=["balance"])
    async def points_cmd(self, ctx: commands.Context, target: str = "") -> None:
        target = target.strip().lstrip("@")
        if target:
            found = await self._db.find_by_name(target)
            if found is None:
                await self._reply(ctx, f"I haven't seen {self._automod.scrub(target, 32)} in chat yet.")
                return
            await self._reply(ctx, await self._economy.points_line(found[0], found[1]))
            return
        await self._reply(ctx, await self._economy.points_line(str(ctx.chatter.id), display_name_of(ctx.chatter)))

    @commands.command(name="watchtime")
    async def watchtime_cmd(self, ctx: commands.Context) -> None:
        stats = await self._db.get_stats(str(ctx.chatter.id))
        watched = format_duration(stats["watch_seconds"] if stats else 0)
        await self._reply(ctx, f"{display_name_of(ctx.chatter)} has {watched} of chat activity tracked.")

    @commands.command(name="rank")
    async def rank_cmd(self, ctx: commands.Context) -> None:
        await self._reply(ctx, await self._economy.rank_line(str(ctx.chatter.id), display_name_of(ctx.chatter)))

    @commands.command(name="leaderboard", aliases=["top"])
    async def leaderboard_cmd(self, ctx: commands.Context, kind: str = "") -> None:
        by_watch = kind.strip().lower() in ("watch", "watchtime", "time")
        if by_watch:
            rows = [(n, format_duration(v)) for n, v in await self._db.top_watch_seconds(limit=5)]
            label = "Most chat time"
        else:
            rows = [(n, str(v)) for n, v in await self._db.top_points(limit=5)]
            label = "Top points"
        if not rows:
            await self._reply(ctx, "Nobody's on the board yet.")
            return
        ranked = ", ".join(f"{i}. {name} ({value})" for i, (name, value) in enumerate(rows, start=1))
        await self._reply(ctx, f"{label}: {ranked}")

    @commands.command(name="daily")
    async def daily_cmd(self, ctx: commands.Context) -> None:
        await self._reply(ctx, await self._economy.daily(str(ctx.chatter.id), display_name_of(ctx.chatter)))

    @commands.command(name="give", aliases=["pay"])
    async def give_cmd(self, ctx: commands.Context, target: str = "", amount: str = "") -> None:
        reply = await self._economy.give(str(ctx.chatter.id), display_name_of(ctx.chatter), target, amount)
        await self._reply(ctx, reply)

    @commands.command(name="gamble", aliases=["bet"])
    async def gamble_cmd(self, ctx: commands.Context, bet: str = "") -> None:
        await self._reply(ctx, await self._economy.gamble(str(ctx.chatter.id), display_name_of(ctx.chatter), bet))
