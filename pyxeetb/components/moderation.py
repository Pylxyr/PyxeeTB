from __future__ import annotations

import logging
from dataclasses import fields
from typing import TYPE_CHECKING

from twitchio.ext import commands

from pyxeetb.textutil import parse_int, parse_uint
from pyxeetb.toggles import TOGGLE_KEYS
from pyxeetb.tunables import TUNABLE_BOUNDS, TwitchTunables

if TYPE_CHECKING:
    from pyxeetb.actions import Reply
    from pyxeetb.automod import AutoMod
    from pyxeetb.settings import LiveSettings

log = logging.getLogger(__name__)


def keys_hint(keys: list[str] | tuple[str, ...], budget: int = 300) -> str:
    """As many keys as fit in a chat message, then an ellipsis."""
    shown: list[str] = []
    used = 0
    for key in keys:
        used += len(key) + 2
        if used > budget:
            return ", ".join(shown) + ", … (full list on /settings)"
        shown.append(key)
    return ", ".join(shown)


# Settings that move points or let the bot delete/time out people are the
# broadcaster's call: a moderator can read them but not change them from chat.
# (The /settings page is the broadcaster's own, behind its own sign-in.)
_BROADCASTER_ONLY_GROUPS = frozenset({"Points & rewards", "Gambling"})
BROADCASTER_ONLY_TUNABLES = frozenset(
    f.name for f in fields(TwitchTunables) if f.metadata["group"] in _BROADCASTER_ONLY_GROUPS
)
BROADCASTER_ONLY_TOGGLES = frozenset(
    {"gamble_enabled", "duels_enabled", "filter_delete_enabled", "filter_timeout_enabled", "stream_summary_enabled"}
)


def _is_broadcaster(ctx: commands.Context) -> bool:
    return bool(getattr(ctx.chatter, "broadcaster", False))


USAGE = {
    "setlimit": "Usage: !setlimit <key> [value] — keys: " + keys_hint(list(TUNABLE_BOUNDS)),
    "toggle": "Usage: !toggle <key> [on|off] — keys: " + keys_hint(list(TOGGLE_KEYS)),
}


class ModerationComponent(commands.Component):
    """Runtime settings and chat-filter management (mod-only; the broadcaster
    always passes `is_moderator`)."""

    def __init__(self, reply: Reply, settings: LiveSettings, automod: AutoMod) -> None:
        self._reply = reply
        self._settings = settings
        self._automod = automod

    @commands.is_moderator()
    @commands.command(name="setlimit")
    async def set_limit(self, ctx: commands.Context, *, args: str = "") -> None:
        """!setlimit <key> shows a value and its range; !setlimit <key> <value> sets it."""
        parts = args.split()
        if not parts:
            await self._reply(ctx, USAGE["setlimit"])
            return
        key = parts[0]
        bounds = TUNABLE_BOUNDS.get(key)
        if bounds is None:
            await self._reply(ctx, f"Unknown key {key!r} — keys: {keys_hint(list(TUNABLE_BOUNDS), 250)}")
            return
        lo, hi = bounds
        if len(parts) == 1:
            current = self._settings.tunables.to_dict()[key]
            await self._reply(ctx, f"{key} = {current} (allowed {lo}-{hi})")
            return
        parsed_value = parse_int(parts[1])
        if parsed_value is None:
            await self._reply(ctx, f"{key}: not a number.")
            return
        value = parsed_value
        if not lo <= value <= hi:
            await self._reply(ctx, f"{key}: must be between {lo} and {hi}.")
            return
        if key in BROADCASTER_ONLY_TUNABLES and not _is_broadcaster(ctx):
            await self._reply(ctx, f"Only the broadcaster can change {key}.")
            return

        await self._settings.set_tunable(key, value)
        log.info("%s = %s set via chat by %s (%s)", key, value, ctx.chatter.display_name, ctx.chatter.id)
        await self._reply(ctx, f"{key} = {value}")

    @commands.is_moderator()
    @commands.command(name="toggle")
    async def toggle(self, ctx: commands.Context, *, args: str = "") -> None:
        """!toggle <key> flips a feature; !toggle <key> on|off sets it."""
        parts = args.split()
        if not parts or len(parts) > 2 or (len(parts) == 2 and parts[1].lower() not in ("on", "off")):
            await self._reply(ctx, USAGE["toggle"])
            return
        key = parts[0]
        if key not in TOGGLE_KEYS:
            await self._reply(ctx, f"Unknown key {key!r} — keys: {keys_hint(list(TOGGLE_KEYS), 250)}")
            return
        explicit = parts[1].lower() == "on" if len(parts) == 2 else None
        if key in BROADCASTER_ONLY_TOGGLES and not _is_broadcaster(ctx):
            await self._reply(ctx, f"Only the broadcaster can change {key}.")
            return
        new_value = (not getattr(self._settings.toggles, key)) if explicit is None else explicit
        await self._settings.set_toggle(key, new_value)
        log.info("%s = %s set via chat by %s (%s)", key, new_value, ctx.chatter.display_name, ctx.chatter.id)
        await self._reply(ctx, f"{key} = {'on' if new_value else 'off'}")

    @commands.is_moderator()
    @commands.command(name="permit")
    async def permit_cmd(self, ctx: commands.Context, user: str = "", seconds: str = "") -> None:
        login = user.strip().lstrip("@").lower()
        if not login:
            await self._reply(ctx, "Usage: !permit <user> [seconds]")
            return
        tunables = self._settings.tunables
        lo, hi = TUNABLE_BOUNDS["permit_default_seconds"]
        requested = parse_uint(seconds)
        length = requested if requested is not None and lo <= requested <= hi else tunables.permit_default_seconds
        self._automod.permit(login, length)
        await self._reply(ctx, f"@{login} may post links for the next {length}s.")

    @commands.is_moderator()
    @commands.command(name="blockterm")
    async def blockterm_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        action, _, term = args.strip().partition(" ")
        action, term = action.lower(), term.strip()
        automod = self._automod
        if action == "add" and term:
            added = await automod.add_term(term, str(ctx.chatter.id))
            await self._reply(ctx, "Blocked that term." if added else "Already blocked.")
        elif action in ("remove", "del") and term:
            removed = await automod.remove_term(term)
            await self._reply(ctx, "Unblocked." if removed else "That term isn't blocked.")
        elif action == "list":
            count = len(automod.matcher.terms)
            await self._reply(ctx, f"{count} blocked term(s) — the list is kept out of chat on purpose; see /settings.")
        else:
            await self._reply(ctx, "Usage: !blockterm add|remove <term> | list  (turn on with !toggle term_filter_enabled)")

    @commands.is_moderator()
    @commands.command(name="allowdomain")
    async def allowdomain_cmd(self, ctx: commands.Context, *, args: str = "") -> None:
        action, _, domain = args.strip().partition(" ")
        action, domain = action.lower(), domain.strip()
        automod = self._automod
        if action == "add" and domain:
            host = await automod.add_domain(domain, str(ctx.chatter.id))
            await self._reply(ctx, f"Links to {host} are allowed." if host else "That doesn't look like a domain.")
        elif action in ("remove", "del") and domain:
            removed = await automod.remove_domain(domain)
            await self._reply(ctx, "Removed." if removed else "That domain wasn't on the list.")
        elif action == "list":
            listing = ", ".join(automod.allowed_domains) or "none"
            await self._reply(ctx, f"Allowed link domains: {listing}")
        else:
            await self._reply(ctx, "Usage: !allowdomain add|remove <domain> | list")
