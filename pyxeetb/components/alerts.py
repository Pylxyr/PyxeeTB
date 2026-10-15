from __future__ import annotations

from typing import TYPE_CHECKING

from twitchio.ext import commands


if TYPE_CHECKING:
    from twitchio import (
        ChannelCheer,
        ChannelFollow,
        ChannelRaid,
        ChannelSubscribe,
        ChannelSubscriptionGift,
        ChannelSubscriptionMessage,
        HypeTrainBegin,
        HypeTrainEnd,
        HypeTrainProgress,
    )

    from pyxeetb.actions import TwitchActions
    from pyxeetb.economy import Economy
    from pyxeetb.settings import LiveSettings

_TIER_NAMES = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3"}


class AlertsComponent(commands.Component):
    """Follow/sub/cheer/raid announcements, gated by one toggle
    (alerts_enabled) regardless of which underlying EventSub subscription
    actually succeeded — see chatbot.py's _try_subscribe_alerts. Listeners
    here are additive (Component.listener(), not an event_message
    override), so they can't interfere with anything else handling the
    same event."""

    def __init__(self, actions: TwitchActions, economy: Economy, settings: LiveSettings) -> None:
        self._actions = actions
        self._economy = economy
        self._settings = settings
        # Highest Hype Train level already seen, so a level-up is announced once.
        self._hype_level = 0

    async def _alerts_on(self) -> bool:
        toggles = self._settings.toggles
        return toggles.alerts_enabled

    @staticmethod
    def _bonus(points: int | None) -> str:
        return f" (+{points} points)" if points else ""

    @commands.Component.listener()
    async def event_follow(self, payload: ChannelFollow) -> None:
        name = payload.user.display_name or payload.user.name or str(payload.user.id)
        # Bonuses are independent of the alerts toggle — only the chat message is gated.
        points = await self._economy.on_follow(str(payload.user.id), name, payload.user.name or "")
        if await self._alerts_on():
            await self._actions.announce(f"Thanks for the follow, {name}! \U0001f49c{self._bonus(points)}")

    @commands.Component.listener()
    async def event_subscription(self, payload: ChannelSubscribe) -> None:
        if payload.gift:
            return  # a gifted sub arrives here once per recipient; the gifter's own
        # event (event_subscription_gift) announces it, so this only handles a
        # self-subscribe — avoids double-announcing one gift as "so-and-so subscribed".
        name = payload.user.display_name or payload.user.name or str(payload.user.id)
        points = await self._economy.on_subscribe(str(payload.user.id), name, payload.user.name or "")
        if await self._alerts_on():
            tier = _TIER_NAMES.get(payload.tier, payload.tier)
            await self._actions.announce(f"Welcome to the club, {name}! ({tier}) \U0001f389{self._bonus(points)}")

    @commands.Component.listener()
    async def event_subscription_message(self, payload: ChannelSubscriptionMessage) -> None:
        """A resubscription the viewer shared in chat. (Twitch only sends this when
        they choose to share it — a silent resub raises no event at all.)"""
        name = payload.user.display_name or payload.user.name or str(payload.user.id)
        points = await self._economy.on_subscribe(str(payload.user.id), name, payload.user.name or "")
        if await self._alerts_on():
            tier = _TIER_NAMES.get(payload.tier, payload.tier)
            months = payload.cumulative_months
            await self._actions.announce(
                f"{name} resubscribed ({tier}) for {months} month{'s' if months != 1 else ''}! "
                f"\U0001f389{self._bonus(points)}"
            )

    @commands.Component.listener()
    async def event_subscription_gift(self, payload: ChannelSubscriptionGift) -> None:
        """Someone gifted one or more subs. The gifter earns the subscription bonus
        for each (capped — see Economy.on_gift_subs); the recipients' own events are
        ignored above so a gift is never announced twice."""
        user = None if payload.anonymous else payload.user
        points = None
        if user is not None:
            name = user.display_name or user.name or str(user.id)
            points = await self._economy.on_gift_subs(str(user.id), name, payload.total, user.name or "")
        else:
            name = "An anonymous gifter"
        if await self._alerts_on():
            tier = _TIER_NAMES.get(payload.tier, payload.tier)
            await self._actions.announce(
                f"{name} gifted {payload.total} {tier} sub{'s' if payload.total != 1 else ''}! "
                f"\U0001f381{self._bonus(points)}"
            )

    @commands.Component.listener()
    async def event_cheer(self, payload: ChannelCheer) -> None:
        points = None
        if payload.user is not None:
            who = payload.user.display_name or payload.user.name or str(payload.user.id)
            points = await self._economy.on_cheer(str(payload.user.id), who, payload.bits, payload.user.name or "")
        if await self._alerts_on():
            name = payload.user.display_name if payload.user else "an anonymous cheerer"
            await self._actions.announce(f"{name} cheered {payload.bits} bits! \U0001fa99{self._bonus(points)}")

    @commands.Component.listener()
    async def event_raid(self, payload: ChannelRaid) -> None:
        if not await self._alerts_on():
            return
        await self._actions.announce(
            f"{payload.from_broadcaster.display_name} is raiding with "
            f"{payload.viewer_count} viewer(s)! \U0001f680"
        )
        # Best-effort and independent of the announcement above — a
        # missing moderator:manage:shoutouts scope (or Twitch's own
        # once-per-2-minutes cooldown, on a raid train) means the
        # announcement still goes out even if this doesn't.
        raider_name = (
            payload.from_broadcaster.display_name
            or payload.from_broadcaster.name
            or str(payload.from_broadcaster.id)
        )
        await self._actions.try_shoutout(payload.from_broadcaster.id, raider_name)

    @commands.Component.listener()
    async def event_hype_train(self, payload: HypeTrainBegin) -> None:
        # twitchio dispatches channel.hype_train.begin as plain `event_hype_train`.
        self._hype_level = payload.level
        if not await self._alerts_on():
            return
        await self._actions.announce(f"\U0001f682 Hype Train started! Goal: {payload.goal} to reach level {payload.level + 1}.")

    @commands.Component.listener()
    async def event_hype_train_progress(self, payload: HypeTrainProgress) -> None:
        # Twitch fires one of these per contribution. `progress` counts points at
        # the *current* level and resets when a level is reached, so a level-up
        # shows as a higher `level`, never as progress >= goal.
        if self._hype_level == 0:  # joined mid-train (no begin event seen): just learn the level
            self._hype_level = payload.level
            return
        if payload.level <= self._hype_level:
            return
        self._hype_level = payload.level
        if not await self._alerts_on():
            return
        await self._actions.announce(f"\U0001f682 Hype Train reached level {payload.level}! \U0001f525")

    @commands.Component.listener()
    async def event_hype_train_end(self, payload: HypeTrainEnd) -> None:
        self._hype_level = 0
        if not await self._alerts_on():
            return
        top = payload.top_contributions[0] if payload.top_contributions else None
        leader = f" Top contributor: {top.user.display_name} ({top.total})." if top and top.user else ""
        await self._actions.announce(f"\U0001f682 Hype Train ended at level {payload.level}!{leader}")

    @commands.is_moderator()
    @commands.command(name="so", aliases=["shoutout"])
    async def shoutout_cmd(self, ctx: commands.Context, *, username: str) -> None:
        """Mod-only manual shoutout — !so <username>. Shares try_shoutout
        with the auto-raid-shoutout above, so it needs the same
        moderator:manage:shoutouts scope (see chatbot.py's module
        docstring); without it this always reports failure."""
        username = username.strip().lstrip("@").lower()
        if not username:
            await self._actions.safe_reply(ctx, "Usage: !so <username>")
            return
        user_id = await self._actions.resolve_user_id(username)
        if user_id is None:
            await self._actions.safe_reply(ctx, f"Couldn't find a Twitch user named {username!r}.")
            return
        if await self._actions.try_shoutout(user_id, username):
            await self._actions.safe_reply(ctx, f"Shouting out {username}!")
        else:
            await self._actions.safe_reply(ctx,
                "Couldn't send that shoutout — check the bot's log (likely a missing scope or Twitch's cooldown)."
            )
