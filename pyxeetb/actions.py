"""Everything the bot *does* in Twitch chat: sending messages, replying,
deleting, timing out, shouting out. One small object the services and
components share, so none of them has to reach into the bot itself — and tests
can hand them a fake.

Also home to the reply decorator: Twitch silently drops a chat message that is
byte-identical to one this account sent recently, so a message is only given a
small rotating cosmetic suffix when it would repeat something sent a moment ago.
Everything else goes out clean.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from twitchio.exceptions import HTTPException, TwitchioException

if TYPE_CHECKING:
    from twitchio import PartialUser
    from twitchio.ext import commands

    from pyxeetb.runtime import RuntimeStatus

log = logging.getLogger(__name__)

# A component sends a reply through one of these instead of holding the bot.
Reply = Callable[["commands.Context", str], Awaitable[None]]
Announce = Callable[[str], Awaitable[None]]

# Twitch's hard limit on a single chat message. PartialUser.send_message raises
# a plain ValueError above it — not a TwitchioException.
MAX_CHAT_MESSAGE_LENGTH = 500

# How far back "sent a moment ago" reaches. Twitch's own window isn't published
# (a repeat has been seen dropped 17s later, even across a restart), so this is a
# generous guess; a miss costs one swallowed message, never an error.
DUPLICATE_WINDOW_SECONDS = 120.0


class ReplyDecorator:
    """Truncates to Twitch's limit and, only when the text would repeat a message
    sent within DUPLICATE_WINDOW_SECONDS, appends the next suffix in rotation."""

    def __init__(
        self,
        suffixes: Sequence[str],
        *,
        window_seconds: float = DUPLICATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._suffixes = tuple(suffixes)
        self._window = window_seconds
        self._clock = clock
        self._sent: deque[tuple[float, str]] = deque()
        self._counter = 0

    @staticmethod
    def _fit(message: str, suffix: str) -> str:
        budget = MAX_CHAT_MESSAGE_LENGTH - len(suffix)
        if len(message) > budget:
            message = message[: budget - 1] + "\u2026"
        return f"{message}{suffix}"

    def decorate(self, message: str) -> str:
        now = self._clock()
        while self._sent and now - self._sent[0][0] > self._window:
            self._sent.popleft()
        recent = {text for _, text in self._sent}
        text = self._fit(message, "")
        if text in recent and self._suffixes:
            for _ in range(len(self._suffixes)):
                suffix = self._suffixes[self._counter % len(self._suffixes)]
                self._counter += 1
                text = self._fit(message, suffix)
                if text not in recent:
                    break
        self._sent.append((now, text))
        return text


class TwitchClient(Protocol):
    """The slice of the twitchio Bot that TwitchActions needs."""

    def create_partialuser(self, user_id: int | str, *args: Any, **kwargs: Any) -> PartialUser: ...

    async def fetch_users(self, *args: Any, **kwargs: Any) -> Any: ...


class TwitchActions:
    def __init__(
        self,
        client: TwitchClient,
        status: RuntimeStatus,
        decorator: ReplyDecorator,
        *,
        bot_id: str,
        owner_id: str,
    ) -> None:
        self._client = client
        self._status = status
        self._decorator = decorator
        self._bot_id = bot_id
        self._owner_id = owner_id

    def _broadcaster(self) -> PartialUser:
        return self._client.create_partialuser(user_id=self._owner_id)

    # -- chat ----------------------------------------------------------------

    async def announce(self, message: str) -> None:
        """Sends a message to the broadcaster's channel (no command Context to
        reply() from — timers, filters, alerts). Best-effort."""
        text = self._decorator.decorate(message)
        try:
            await self._broadcaster().send_message(sender=self._bot_id, message=text)
        except (TwitchioException, ValueError) as e:
            log.info("Announcement not delivered (%s): %r", type(e).__name__, text)

    async def safe_reply(self, ctx: commands.Context, message: str) -> None:
        """ctx.reply() that swallows Twitch's delivery failures (rate limit,
        duplicate-message rule) instead of letting them propagate."""
        text = self._decorator.decorate(message)
        try:
            await ctx.reply(text)
        except (TwitchioException, ValueError) as e:
            log.info("Chat reply not delivered (%s): %r", type(e).__name__, text)

    # -- moderation ------------------------------------------------------------

    def _note_scope_failure(self, scope_key: str, e: HTTPException, what: str, scope: str) -> None:
        if e.status in (401, 403):
            if scope_key not in self._status.scopes_missing:
                log.warning(
                    "%s failed with HTTP %s — the bot's token is probably missing %s. Staying off for "
                    "the rest of this run; see chatbot.py's module docstring for the OAuth step. (%s)",
                    what, e.status, scope, e,
                )
            self._status.scopes_missing.add(scope_key)

    async def try_shoutout(self, to_user_id: str, to_display_name: str) -> bool:
        """Best-effort — shared by the auto-raid-shoutout and !so. Needs
        moderator:manage:shoutouts; a permission failure is remembered so a train
        of raids doesn't repeat the same warning."""
        if "shoutout" in self._status.scopes_missing:
            return False
        try:
            await self._broadcaster().send_shoutout(to_broadcaster=to_user_id, moderator=self._bot_id)
            return True
        except HTTPException as e:
            if e.status in (401, 403):
                self._note_scope_failure("shoutout", e, "Shoutout", "moderator:manage:shoutouts")
            else:
                # Likely Twitch's own shoutout cooldown — routine, not a scope issue.
                log.info("Shoutout to %s not sent (%s) — likely Twitch's own cooldown.", to_display_name, e)
            return False
        except Exception:
            log.warning("Shoutout to %s failed (non-fatal).", to_display_name, exc_info=True)
            return False

    async def delete_message(self, message_id: str) -> bool:
        """Deletes one chat message (needs moderator:manage:chat_messages)."""
        try:
            await self._broadcaster().delete_chat_messages(moderator=self._bot_id, message_id=message_id)
            return True
        except HTTPException as e:
            self._note_scope_failure("delete", e, "Message delete", "moderator:manage:chat_messages")
        except Exception:
            log.warning("Message delete failed (non-fatal).", exc_info=True)
        return False

    async def timeout_user(self, user_id: str, seconds: int, reason: str) -> bool:
        """Times a chatter out (needs moderator:manage:banned_users)."""
        try:
            await self._broadcaster().timeout_user(
                moderator=self._bot_id, user=user_id, duration=seconds, reason=reason
            )
            return True
        except HTTPException as e:
            self._note_scope_failure("timeout", e, "Timeout", "moderator:manage:banned_users")
        except Exception:
            log.warning("Timeout failed (non-fatal).", exc_info=True)
        return False

    async def resolve_user_id(self, login: str) -> str | None:
        """Login name -> user ID, for !so <username> (send_shoutout needs an
        ID, not a login name). Public endpoint, no extra scope needed."""
        try:
            users = await self._client.fetch_users(logins=[login])
        except Exception:
            log.debug("Failed to resolve Twitch login %r to a user ID.", login, exc_info=True)
            return None
        return str(users[0].id) if users else None
