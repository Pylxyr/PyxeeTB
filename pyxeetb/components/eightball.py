from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.eightball import answer

if TYPE_CHECKING:
    from pyxeetb.actions import Reply


class EightBallComponent(commands.Component):
    def __init__(self, reply: Reply) -> None:
        self._reply = reply

    @commands.command(name="8ball")
    async def eightball_cmd(self, ctx: commands.Context, *, question: str = "") -> None:
        if not question.strip():
            await self._reply(ctx, "Usage: !8ball <question>")
            return
        await self._reply(ctx, f"\U0001f3b1 {answer()}")
