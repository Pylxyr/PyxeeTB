"""Twitch chat bot — connection, auth, EventSub plumbing and message routing.

The features live elsewhere: services (automod.py, economy.py, customcommands.py, ...)
hold the logic, components/* are thin command layers handed exactly the services they
use, actions.py is everything the bot *does* in chat, and streamstate.py is what it
knows about the stream. This class wires them together and owns the Twitch connection.

Built against twitchio 3.x's EventSub-based Bot. Auth model: Twitch's "Installed
Chatbot" pattern — one bot account (made a moderator in your channel) plus an OAuth
token for the broadcaster, authorized once through twitchio's built-in web server on
http://localhost:4343 and persisted to data/twitch_tokens.json. The README has the
step-by-step walkthrough, including the exact scope URLs; `_log_token_diagnostics`
catches the most common mistake (authorizing the same account twice).

Every optional feature is gated by its own toggle (see toggles.py) and degrades
independently when its OAuth scope is missing: a sticky flag logs the failure once and
stops retrying (see actions.py).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from twitchio import eventsub
from twitchio.ext import commands

from pyxeetb.actions import ReplyDecorator, TwitchActions
from pyxeetb.automod import AutoMod
from pyxeetb.chatevent import ChatEvent, display_name_of
from pyxeetb.chatfeed import ChatFeed, fragments_to_dicts
from pyxeetb.commands_reference import BY_NAME
from pyxeetb.components.alerts import AlertsComponent
from pyxeetb.components.counters import CountersComponent
from pyxeetb.components.custom_commands import CustomCommandsComponent
from pyxeetb.components.economy import EconomyComponent
from pyxeetb.components.eightball import EightBallComponent
from pyxeetb.components.games import GamesComponent
from pyxeetb.components.giveaway import GiveawayComponent
from pyxeetb.components.info import InfoComponent
from pyxeetb.components.moderation import USAGE as _MODERATION_USAGE
from pyxeetb.components.moderation import ModerationComponent
from pyxeetb.components.predictions import PredictionsComponent
from pyxeetb.components.predictions import build_manager as build_prediction_manager
from pyxeetb.components.queue import QueueComponent
from pyxeetb.components.quotes import QuotesComponent
from pyxeetb.components.stream_info import StreamInfoComponent
from pyxeetb.components.timers import TimersComponent
from pyxeetb.counters import CounterStore, split_suffix
from pyxeetb.customcommands import CustomCommandStore
from pyxeetb.emotes import PROVIDERS as EMOTE_PROVIDERS
from pyxeetb.emotes import EmoteService
from pyxeetb.db import Database
from pyxeetb.duels import DuelManager
from pyxeetb.economy import AWARD_TICK_SECONDS, Economy
from pyxeetb.cheermotes import CheermoteService
from pyxeetb.giveaway import GiveawayManager
from pyxeetb.queue import ViewerQueue
from pyxeetb.runtime import DEFAULT_REPLY_SUFFIXES, RuntimeStatus
from pyxeetb.settings import LiveSettings
from pyxeetb.streamstate import Reading, StreamState
from pyxeetb.throttle import CommandThrottle, UsageCounter

if TYPE_CHECKING:
    from twitchio import (
        ChannelChatClearUserMessages,
        ChatMessage,
        ChatMessageDelete,
        ChannelUpdate,
        StreamOffline,
        StreamOnline,
    )
    from twitchio.authentication import ValidateTokenPayload
    from twitchio.payloads import TokenRefreshedPayload

log = logging.getLogger(__name__)

# Per-command usage strings for event_command_error's MissingRequiredArgument
# handler below. Keyed by canonical command name, not alias.
_USAGE = dict(_MODERATION_USAGE)

# How often buffered command-usage counts are written to the database.
_USAGE_FLUSH_SECONDS = 60.0


class TwitchChatBot(commands.Bot):
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        bot_id: str,
        owner_id: str,
        prefix: str,
        public_base_url: str | None,
        chat_feed: ChatFeed,
        settings: LiveSettings,
        db: Database,
        token_storage_path: Path,
        status: RuntimeStatus,
        reply_suffixes: tuple[str, ...] = DEFAULT_REPLY_SUFFIXES,
        reserved_commands: frozenset[str] = frozenset(),
        emote_providers: tuple[str, ...] = EMOTE_PROVIDERS,
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id,
            owner_id=owner_id,
            prefix=prefix,
        )
        self.chat_feed = chat_feed
        self.settings = settings
        self.db = db
        self.status = status
        self.prefix = prefix
        # Defaults to the GitHub Pages commands page (config.DEFAULT_PUBLIC_BASE_URL);
        # None only when TWITCH_PUBLIC_BASE_URL=none — then !commands falls back to
        # the terse in-chat listing.
        self.public_commands_url = f"{public_base_url}/commands" if public_base_url else None
        self._channel_id = owner_id
        self._bot_account_id = bot_id
        self._token_storage_path = token_storage_path
        # Every name a mod may not reuse for a custom command: our own commands
        # and aliases, plus whatever another bot in the channel answers to.
        self.reserved_names: frozenset[str] = frozenset(BY_NAME) | reserved_commands
        # Chat messages seen since startup (excluding the bot's own) — the
        # timers use it so they never talk to an empty room.
        self.chat_messages = 0
        self._points_task: asyncio.Task[None] | None = None
        self._usage_task: asyncio.Task[None] | None = None
        self._cheermotes_task: asyncio.Task[None] | None = None
        self._emotes_task: asyncio.Task[None] | None = None

        # Services (the logic) — the components are thin command layers over these.
        self.actions = TwitchActions(
            self, status, ReplyDecorator(reply_suffixes), bot_id=bot_id, owner_id=owner_id
        )
        self.stream = StreamState(status, self._read_stream, on_live_start=lambda: self.economy.reset_session())
        self.cheermotes = CheermoteService(self._fetch_cheermotes)
        # 7TV / BTTV / FFZ: own aiohttp session and refresh task, never on the chat path.
        self.emotes = EmoteService(broadcaster_id=owner_id, sources=emote_providers)
        self.throttle = CommandThrottle()
        self.usage = UsageCounter()
        self.economy = Economy(
            db,
            settings,
            status,
            is_live=self.stream.is_live,
            scrub=lambda text: self.automod.scrub(text, 32),
        )
        self.automod = AutoMod(
            db,
            settings,
            status,
            announce=self.actions.announce,
            delete_message=self.actions.delete_message,
            timeout_user=self.actions.timeout_user,
        )
        self.custom = CustomCommandStore(db)
        self.counters = CounterStore(db)
        self.viewer_queue = ViewerQueue()
        self.giveaway = GiveawayManager()
        self.duels = DuelManager(db)
        self.predictions = build_prediction_manager(self.create_partialuser(user_id=owner_id))

    async def load_tokens(self, path: str | None = None, /) -> None:
        # Redirects TwitchIO's default token file into DATA_DIR instead.
        self._token_storage_path.parent.mkdir(parents=True, exist_ok=True)
        await super().load_tokens(path or str(self._token_storage_path))

    async def save_tokens(self, path: str | None = None, /) -> None:
        """Writes tokens to disk, locks the file down, and retries the chat
        subscription (a no-op once already subscribed). twitchio's Client
        only calls this on a graceful close — add_token() and
        event_token_refreshed() below call it explicitly too, so completing
        OAuth or a routine refresh takes effect immediately instead of only
        persisting at the next restart."""
        self._token_storage_path.parent.mkdir(parents=True, exist_ok=True)
        target = path or str(self._token_storage_path)
        await super().save_tokens(target)
        # twitchio's save() writes with no explicit mode, so this (live
        # OAuth tokens) inherits the process umask — often world-readable.
        # Locked down the same way setup.sh locks .env; reapplied every
        # save since a fresh write resets permissions.
        with contextlib.suppress(OSError):
            Path(target).chmod(0o600)
        await self._try_subscribe_chat()
        await self._try_subscribe_alerts()

    async def add_token(self, token: str, refresh: str) -> ValidateTokenPayload:
        """twitchio calls this the instant an OAuth authorization completes,
        well before setup_hook() or any later save_tokens() call — the base
        class otherwise only calls save_tokens() from Client.close()."""
        response = await super().add_token(token, refresh)
        await self.save_tokens()
        return response

    async def event_token_refreshed(self, payload: TokenRefreshedPayload) -> None:
        """twitchio dispatches this after silently refreshing a
        soon-to-expire token — without this, the refreshed pair only lives
        in memory until the next graceful close, so a crash in between
        loads a stale, already-rotated token and forces re-authorization."""
        await self.save_tokens()

    def _oauth_complete(self) -> bool:
        if not self._token_storage_path.exists():
            return False
        try:
            saved_ids = set(json.loads(self._token_storage_path.read_text(encoding="utf-8")))
        except Exception:
            return False
        return self._bot_account_id in saved_ids and self._channel_id in saved_ids

    async def _read_stream(self) -> Reading:
        """One Helix lookup for StreamState: live-ness plus title and category."""
        broadcaster = self.create_partialuser(user_id=self._channel_id)
        stream = await broadcaster.fetch_stream()
        if stream is not None:
            return Reading(True, stream.started_at, stream.title or "", stream.game_name or "")
        info = await broadcaster.fetch_channel_info()
        return Reading(False, None, info.title or "", info.game_name or "")

    async def _fetch_cheermotes(self) -> list[Any]:
        # App-token request (no user token needed): global cheermotes plus the
        # broadcaster's custom ones.
        return list(await self.fetch_cheermotes(broadcaster_id=self._channel_id))

    def _log_token_diagnostics(self) -> None:
        # Catches the single most common cause of "OAuth said success but
        # chat still doesn't work": the saved token belongs to a different
        # Twitch account than TWITCH_BOT_ID/TWITCH_OWNER_ID, from reusing an
        # already-logged-in browser session for both authorization steps.
        if not self._token_storage_path.exists():
            return
        try:
            saved_ids = set(json.loads(self._token_storage_path.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("Couldn't read %s to check saved tokens: %s", self._token_storage_path, e)
            return
        if self._bot_account_id not in saved_ids:
            log.error(
                "No saved token for TWITCH_BOT_ID=%s in %s (tokens on file: %s). Chat commands "
                "won't work. Redo the bot-account OAuth step — make sure the browser is actually "
                "logged into THAT account, not your broadcaster account (a private/incognito "
                "window avoids reusing whatever session is already active).",
                self._bot_account_id,
                self._token_storage_path,
                sorted(saved_ids) or "none",
            )
        if self._channel_id not in saved_ids:
            log.info(
                "No saved token for TWITCH_OWNER_ID=%s — fine if the bot account is already a "
                "moderator in your channel (that alone satisfies the chat subscription), "
                "otherwise redo the broadcaster-account OAuth step.",
                self._channel_id,
            )

    async def event_ready(self) -> None:
        log.info("Twitch chat bot ready (bot_id=%s).", self._bot_account_id)

    async def _try_subscribe_chat(self) -> None:
        if self.status.chat_subscribed:
            return
        self._log_token_diagnostics()
        subscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self._channel_id,
            user_id=self._bot_account_id,
        )
        try:
            await self.subscribe_websocket(payload=subscription)
            log.info("Subscribed to chat messages for broadcaster=%s bot=%s", self._channel_id, self._bot_account_id)
            self.status.chat_subscribed = True
        except Exception as e:
            if self._oauth_complete():
                log.exception(
                    "Chat subscription failed even though both accounts have saved tokens — "
                    "chat commands won't work until this is fixed. See the token diagnostics "
                    "logged above, or redo the OAuth steps in README.md with &force_verify=true "
                    "if a token was revoked or scopes changed. Error: %s",
                    e,
                )
            else:
                log.warning(
                    "Skipping chat subscription for now — the one-time OAuth steps in "
                    "README.md aren't done for both accounts yet at %s. Will retry "
                    "automatically as soon as a token is saved, no restart needed. Error: %s",
                    self._token_storage_path,
                    e,
                )

    async def _try_subscribe_alerts(self) -> None:
        """Follow/sub/cheer/raid and stream online/offline EventSub subscriptions.
        Independent of the feature toggles (subscribing has no side effects; the
        toggles only gate what an arriving event *says*) and of each other. Re-run
        from save_tokens() so a scope granted after startup is picked up without a
        restart."""
        attempts = (
            (
                "follow",
                eventsub.ChannelFollowSubscription(broadcaster_user_id=self._channel_id, moderator_user_id=self._bot_account_id),
            ),
            ("subscription", eventsub.ChannelSubscribeSubscription(broadcaster_user_id=self._channel_id)),
            # Resubscribes and gifted subs are separate events from a new subscription.
            ("subscription_message", eventsub.ChannelSubscribeMessageSubscription(broadcaster_user_id=self._channel_id)),
            ("subscription_gift", eventsub.ChannelSubscriptionGiftSubscription(broadcaster_user_id=self._channel_id)),
            ("cheer", eventsub.ChannelCheerSubscription(broadcaster_user_id=self._channel_id)),
            ("raid", eventsub.ChannelRaidSubscription(to_broadcaster_user_id=self._channel_id)),
            # Keep the public overlay in step with Twitch-side moderation.
            (
                "message_delete",
                eventsub.ChatMessageDeleteSubscription(broadcaster_user_id=self._channel_id, user_id=self._bot_account_id),
            ),
            (
                "chat_clear_user",
                eventsub.ChatClearUserMessagesSubscription(broadcaster_user_id=self._channel_id, user_id=self._bot_account_id),
            ),
            ("stream_online", eventsub.StreamOnlineSubscription(broadcaster_user_id=self._channel_id)),
            ("stream_offline", eventsub.StreamOfflineSubscription(broadcaster_user_id=self._channel_id)),
            # Title / category changes keep !title and !game current without polling.
            ("channel_update", eventsub.ChannelUpdateSubscription(broadcaster_user_id=self._channel_id)),
            ("hype_train_begin", eventsub.HypeTrainBeginSubscription(broadcaster_user_id=self._channel_id)),
            ("hype_train_progress", eventsub.HypeTrainProgressSubscription(broadcaster_user_id=self._channel_id)),
            ("hype_train_end", eventsub.HypeTrainEndSubscription(broadcaster_user_id=self._channel_id)),
            # Needs channel:manage:predictions (the same scope !predict itself
            # needs to create/end one) — subscribing costs nothing extra if
            # that scope is already missing, this attempt just also fails.
            ("prediction_end", eventsub.ChannelPredictionEndSubscription(broadcaster_user_id=self._channel_id)),
        )
        for name, subscription in attempts:
            if self.status.alert_subscriptions.get(name):
                continue
            try:
                await self.subscribe_websocket(payload=subscription)
                self.status.alert_subscriptions[name] = True
                log.info("Subscribed to %s events.", name)
            except Exception as e:
                # Routine, not a warning — most optional scopes are never granted.
                self.status.alert_subscriptions.setdefault(name, False)
                log.info("Skipping %s events for now (%s) — see module docstring for the optional scope.", name, e)

    async def setup_hook(self) -> None:
        await self.automod.load()
        await self.custom.load()
        await self.counters.load()
        for component in self.build_components():
            await self.add_component(component)
        await self._try_subscribe_chat()
        await self._try_subscribe_alerts()
        self._points_task = asyncio.create_task(self._points_award_loop(), name="points-award-loop")
        self._usage_task = asyncio.create_task(self._usage_flush_loop(), name="command-usage")
        self._cheermotes_task = asyncio.create_task(self.cheermotes.run(), name="cheermotes")
        self._emotes_task = asyncio.create_task(self.emotes.run(), name="chat-emotes")

    def build_components(self) -> list[commands.Component]:
        """The command layers, each handed exactly the services it uses."""
        reply, announce = self.actions.safe_reply, self.actions.announce
        return [
            ModerationComponent(reply, self.settings, self.automod),
            InfoComponent(reply, self.prefix, self.public_commands_url, self.counters),
            EconomyComponent(reply, self.economy, self.db, self.automod),
            CustomCommandsComponent(reply, self.custom, self.counters, self.reserved_names),
            TimersComponent(
                reply, announce, self.db, self.settings, lambda: self.chat_messages, self.stream.is_live
            ),
            AlertsComponent(self.actions, self.economy, self.settings),
            StreamInfoComponent(
                reply, self.stream, lambda: self.create_partialuser(user_id=self._channel_id), self._bot_account_id
            ),
            QuotesComponent(reply, self.db),
            EightBallComponent(reply),
            CountersComponent(reply, self.counters, self.custom, self.reserved_names),
            GamesComponent(reply, self.duels, self.db, self.settings, self.automod),
            QueueComponent(reply, self.viewer_queue, self.settings),
            GiveawayComponent(reply, self.giveaway),
            PredictionsComponent(reply, announce, self.predictions),
        ]

    # -- command hooks ----------------------------------------------------

    async def global_guard(self, ctx: commands.Context) -> bool:
        """Runs before every built-in command: throttles spam (silently — see
        throttle.py). Moderators and the broadcaster are exempt."""
        chatter = ctx.chatter
        name = ctx.command.name if ctx.command is not None else ""
        return self.throttle.allow(name, str(chatter.id), exempt=bool(getattr(chatter, "moderator", False)))

    async def after_invoke(self, ctx: commands.Context) -> None:
        """Counts a built-in command that passed its guards (see throttle.UsageCounter)."""
        if ctx.command is not None:
            self.usage.record(ctx.command.name)

    async def _usage_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_USAGE_FLUSH_SECONDS)
            await self.usage.flush(self.db)

    # -- incoming chat ----------------------------------------------------

    async def event_message(self, message: ChatMessage) -> None:
        # super() first and unconditionally — Bot.event_message is what
        # dispatches commands, so skipping it would silently break every command.
        await super().event_message(message)
        try:
            await self._process_chat(message)
        except Exception:
            # Bookkeeping must never take command handling down with it.
            log.exception("Chat processing failed for message %s.", getattr(message, "id", "?"))

    async def _process_chat(self, message: ChatMessage) -> None:
        chatter = message.chatter
        if chatter is None or str(chatter.id) == self._bot_account_id:
            return
        name = display_name_of(chatter)
        try:
            fragments: list[dict[str, object]] = self.cheermotes.decorate(
                self.emotes.decorate(fragments_to_dicts(message.fragments))
            )
        except Exception:
            # Emote artwork is cosmetic: the message still reaches the overlay
            # (and the filters) as plain text.
            log.debug("Building cheermote fragments failed (non-fatal).", exc_info=True)
            fragments = []
        self.chat_messages += 1
        self.status.last_chat_message_at = time.monotonic()
        event = ChatEvent(
            user_id=str(chatter.id),
            login=chatter.name or "",
            name=name,
            text=message.text,
            message_id=str(getattr(message, "id", "") or ""),
            fragments=fragments,
            is_moderator=bool(chatter.moderator),
            is_vip=bool(chatter.vip),
            is_subscriber=bool(chatter.subscriber),
        )
        self.economy.note_activity(event)
        # AutoMod runs before the overlay sees the message: the overlay (and the
        # public /chat.json and /ws/chat that feed it) is on stream and open to
        # anyone, so a message that breaks the rules must never reach it, not
        # appear and then get removed. If AutoMod itself fails the message is
        # still shown — a broken filter shouldn't blank the overlay.
        violation = None
        try:
            violation = await self.automod.inspect(event)
        except Exception:
            log.exception("AutoMod failed on message %s.", event.message_id or "?")
        finally:
            if violation is None:
                self.chat_feed.append(
                    name,
                    message.text,
                    fragments=fragments or None,
                    message_id=event.message_id,
                    user_id=event.user_id,
                )

    # -- live state and passive points -------------------------------------

    async def event_message_delete(self, payload: ChatMessageDelete) -> None:
        """A moderator (or AutoMod) removed one message on Twitch: take it off
        the public overlay too."""
        if self.chat_feed.remove_message(str(payload.message_id)):
            log.debug("Removed deleted message %s from the chat overlay.", payload.message_id)

    async def event_chat_clear_user(self, payload: ChannelChatClearUserMessages) -> None:
        """A user was banned or timed out and had their messages cleared."""
        removed = self.chat_feed.remove_user(str(payload.user.id))
        if removed:
            log.debug("Removed %d message(s) from the chat overlay for user %s.", removed, payload.user.id)

    async def event_stream_online(self, payload: StreamOnline) -> None:
        self.stream.set_live(True, payload.started_at)
        log.info("Stream went live.")

    async def event_stream_offline(self, payload: StreamOffline) -> None:
        flipped = self.stream.set_live(False)
        log.info("Stream went offline.")
        if not flipped:
            return
        self.giveaway.cancel()  # a giveaway doesn't carry over into the next stream
        summary = self.economy.session_summary()
        if self.settings.toggles.stream_summary_enabled and summary:
            await self.actions.announce(f"Thanks for hanging out! {summary}")
        self.economy.reset_session()

    async def event_channel_update(self, payload: ChannelUpdate) -> None:
        self.stream.apply_channel_update(payload.title or "", payload.category_name or "")

    async def _points_award_loop(self) -> None:
        while True:
            await asyncio.sleep(AWARD_TICK_SECONDS)
            try:
                await self.economy.award_tick()
            except Exception:
                log.exception("Points award tick failed (non-fatal).")

    # -- errors -----------------------------------------------------------

    async def _try_custom_command(self, ctx: commands.Context, name: str) -> bool:
        content = getattr(ctx, "content", "") or ""
        args = content[len(self.prefix) + len(name) :].strip() if content.startswith(self.prefix) else ""
        chatter = ctx.chatter
        channel = display_name_of(ctx.broadcaster) or "the channel"
        tunables = self.settings.tunables
        reply = await self.custom.execute(
            name,
            user=display_name_of(chatter),
            args=args,
            channel=str(channel),
            default_cooldown=tunables.custom_command_cooldown_seconds,
            owner=bool(getattr(chatter, "broadcaster", False)),
            sanitize=lambda text: self.automod.scrub(text, 200),
        )
        if reply is None:
            return False
        await self.actions.safe_reply(ctx, reply)
        return True

    async def _try_counter_command(self, ctx: commands.Context, token: str) -> bool:
        """`!<name>` shows a counter's value; `!<name>++`/`!<name>--` adjusts
        it (mod-only unless the counter is marked public — see counters.py).
        `token` is tried as-is (case already lowered by the caller), so this
        only ever matches a real counter name, with or without the suffix."""
        split = split_suffix(token)
        if split is None:
            return False
        name, suffix = split
        if suffix is None:
            reply = self.counters.view(name)
        else:
            reply = await self.counters.apply_suffix(
                name, suffix, is_moderator=bool(getattr(ctx.chatter, "moderator", False))
            )
        if reply is None:
            return False
        await self.actions.safe_reply(ctx, reply)
        return True

    async def event_command_error(self, payload: commands.CommandErrorPayload) -> None:
        exc = payload.exception
        ctx = payload.context
        if isinstance(exc, commands.CommandNotFound):
            # Fires for every prefixed message that isn't ours — with another bot
            # sharing "!" that's most of them, so try a custom command, then a
            # counter (both dict lookups, no database hit) before giving up quietly.
            content = getattr(ctx, "content", "") or ""
            if content.startswith(self.prefix):
                parts = content[len(self.prefix) :].split(maxsplit=1)
                if parts:
                    token = parts[0].lower()
                    with contextlib.suppress(Exception):
                        if not await self._try_custom_command(ctx, token):
                            await self._try_counter_command(ctx, token)
            return
        if isinstance(exc, commands.GuardFailure):
            # Stay quiet: replying to every non-mod who tries a mod command is
            # chat noise (and, with another bot sharing the prefix, often wrong).
            log.debug("Guard failure for %r", getattr(ctx, "content", ""))
            return
        if isinstance(exc, commands.MissingRequiredArgument):
            name = ctx.command.name if ctx.command is not None else None
            usage = _USAGE.get(name) if name else None
            await self.actions.safe_reply(ctx, usage or f"Missing an argument for {self.prefix}{name or 'that command'}.")
            return
        if isinstance(exc, commands.BadArgument):
            await self.actions.safe_reply(ctx, "I couldn't understand that argument.")
            return
        log.error("Command error in %r: %r", getattr(ctx, "content", "<unknown>"), exc, exc_info=exc)

    async def close(self, **options: Any) -> None:
        """Deliberately doesn't close self.db — the admin server outlives this
        object during shutdown, so bot.py creates and closes the database itself
        after the HTTP surface is down. `**options` (e.g. `save_tokens`) passes
        straight through to commands.Bot.close/Client.close."""
        for task in (self._points_task, self._usage_task, self._cheermotes_task, self._emotes_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._points_task = self._usage_task = self._cheermotes_task = self._emotes_task = None
        await self.usage.flush(self.db)
        await super().close(**options)
