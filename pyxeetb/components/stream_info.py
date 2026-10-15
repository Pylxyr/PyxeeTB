from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from twitchio.exceptions import HTTPException
from twitchio.ext import commands

from pyxeetb.cooldown import CooldownTracker
from pyxeetb.textutil import parse_uint

if TYPE_CHECKING:
    from collections.abc import Callable

    from twitchio import PartialUser

    from pyxeetb.actions import Reply
    from pyxeetb.streamstate import StreamState

log = logging.getLogger(__name__)

_CLIP_COOLDOWN_SECONDS = 10.0
_CLIP_COOLDOWN_KEY = "global"
_CLIP_USER_COOLDOWN_SECONDS = 60.0


class StreamInfoComponent(commands.Component):
    """!uptime/!title/!game answer from the cached stream state (kept current by
    EventSub — no Twitch API call per command); !followage, !clip, and !poll each
    need one of the optional extended scopes documented in chatbot.py's module
    docstring, and each fails gracefully (a friendly chat reply, not a crash) when
    its scope isn't granted. Per-chatter throttling is applied centrally."""

    def __init__(
        self, reply: Reply, stream: StreamState, broadcaster: Callable[[], PartialUser], bot_id: str
    ) -> None:
        self._reply = reply
        self._stream = stream
        self._broadcaster = broadcaster
        self._bot_id = bot_id
        self._followage_scope_missing = False
        self._clip_cooldown = CooldownTracker()

    @commands.command(name="uptime")
    async def uptime_cmd(self, ctx: commands.Context) -> None:
        uptime = await self._stream.uptime()
        if uptime is None:
            await self._reply(ctx, "Not live right now.")
            return
        hours, minutes = divmod(int(uptime.total_seconds() // 60), 60)
        await self._reply(ctx, f"Live for {hours}h {minutes}m.")

    @commands.command(name="title")
    async def title_cmd(self, ctx: commands.Context) -> None:
        info = await self._stream.channel_info()
        if info is None:
            await self._reply(ctx, "Couldn't check that right now.")
            return
        await self._reply(ctx, f"Title: {info[0]}")

    @commands.command(name="game")
    async def game_cmd(self, ctx: commands.Context) -> None:
        info = await self._stream.channel_info()
        if info is None:
            await self._reply(ctx, "Couldn't check that right now.")
            return
        await self._reply(ctx, f"Category: {info[1] or 'none set'}")

    @commands.command(name="followage")
    async def followage_cmd(self, ctx: commands.Context) -> None:
        """Needs moderator:read:followers on the bot's token — see
        chatbot.py's module docstring. token_for is the bot explicitly
        (not left to default to the broadcaster's own token), since that's
        whichever account the scope is actually granted to."""
        if self._followage_scope_missing:
            await self._reply(ctx, "Follow lookups aren't set up for this bot yet.")
            return
        try:
            result = await self._broadcaster().fetch_followers(
                user=ctx.chatter.id, first=1, token_for=self._bot_id
            )
        except HTTPException as e:
            if e.status in (401, 403):
                self._followage_scope_missing = True
                log.warning(
                    "!followage failed with HTTP %s — the bot's token is probably missing "
                    "moderator:read:followers. Staying off for the rest of this run. (%s)",
                    e.status, e,
                )
                await self._reply(ctx, "Follow lookups aren't set up for this bot yet.")
            else:
                log.warning("!followage lookup failed (non-fatal): %s", e)
                await self._reply(ctx, "Couldn't check that right now.")
            return
        except Exception:
            log.warning("!followage lookup failed (non-fatal).", exc_info=True)
            await self._reply(ctx, "Couldn't check that right now.")
            return
        if result.total == 0:
            await self._reply(ctx, "You're not following.")
            return
        async for event in result.followers:
            days = (datetime.datetime.now(datetime.timezone.utc) - event.followed_at).days
            await self._reply(ctx, f"Following for {days} day(s) (since {event.followed_at:%Y-%m-%d}).")
            return
        await self._reply(ctx, "Couldn't check that right now.")

    @commands.command(name="clip")
    async def clip_cmd(self, ctx: commands.Context) -> None:
        """Needs clips:edit on the BROADCASTER's token — see chatbot.py's
        module docstring. Small global (not per-chatter) cooldown so
        several chatters spamming !clip at once doesn't hammer the API for
        what's usually the same moment anyway."""
        is_mod = bool(getattr(ctx.chatter, "moderator", False))
        user_key = f"user:{ctx.chatter.id}"
        if not is_mod and self._clip_cooldown.remaining(user_key, _CLIP_USER_COOLDOWN_SECONDS) > 0:
            return  # one clip a minute per chatter; silent
        remaining = self._clip_cooldown.remaining(_CLIP_COOLDOWN_KEY, _CLIP_COOLDOWN_SECONDS)
        if remaining > 0:
            await self._reply(ctx, f"Just made one — try again in {remaining:.0f}s.")
            return
        self._clip_cooldown.mark(_CLIP_COOLDOWN_KEY)
        self._clip_cooldown.mark(user_key)
        try:
            clip = await self._broadcaster().create_clip(token_for=str(self._broadcaster().id))
        except HTTPException as e:
            if e.status in (401, 403):
                await self._reply(ctx, "Clips aren't set up for this channel yet.")
            else:
                await self._reply(ctx, "Couldn't create a clip right now — is the stream live?")
            log.warning("!clip failed: %s", e)
            return
        except Exception:
            log.warning("!clip failed (non-fatal).", exc_info=True)
            await self._reply(ctx, "Couldn't create a clip right now — is the stream live?")
            return
        await self._reply(ctx, f"Clip created: https://clips.twitch.tv/{clip.id}")

    @commands.is_moderator()
    @commands.command(name="poll")
    async def poll_cmd(self, ctx: commands.Context, *, args: str) -> None:
        """Mod-only: !poll <seconds> <question> ; <choice 1> ; <choice 2> [; up to 3 more].
        Needs channel:manage:polls on the BROADCASTER's token — see
        chatbot.py's module docstring."""
        usage = "Usage: !poll <seconds> <question> ; <choice 1> ; <choice 2> [; ...]"
        parts = args.strip().split(maxsplit=1)
        if len(parts) != 2:
            await self._reply(ctx, usage)
            return
        duration = parse_uint(parts[0])
        if duration is None:
            await self._reply(ctx, usage)
            return
        if not (15 <= duration <= 1800):
            await self._reply(ctx, "Duration must be between 15 and 1800 seconds.")
            return
        segments = [s.strip() for s in parts[1].split(";") if s.strip()]
        if len(segments) < 3:
            await self._reply(ctx, usage)
            return
        title, all_choices = segments[0], segments[1:]
        choices = all_choices[:5]
        try:
            poll = await self._broadcaster().create_poll(title=title, choices=choices, duration=duration)
        except ValueError as e:
            await self._reply(ctx, str(e))
            return
        except HTTPException as e:
            if e.status in (401, 403):
                await self._reply(ctx, "Polls aren't set up for this channel yet.")
            else:
                await self._reply(ctx, "Couldn't start that poll — is one already running?")
            log.warning("!poll failed: %s", e)
            return
        except Exception:
            log.warning("!poll failed (non-fatal).", exc_info=True)
            await self._reply(ctx, "Couldn't start that poll right now.")
            return
        note = f" (only the first 5 of {len(all_choices)} choices were used)" if len(all_choices) > 5 else ""
        await self._reply(ctx, f"Poll started: {poll.title} ({duration}s){note}")
