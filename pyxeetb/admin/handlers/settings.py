"""The proxy-gated route: /settings (view and save)."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from pyxeetb.admin.context import AdminContext, client_ip, get_ctx
from pyxeetb.admin.handlers.auth import authorize, origin_ok, protect
from pyxeetb.admin.render.settings_page import FORM_MARKER, LiveStatus, render_settings_page
from pyxeetb.toggles import TOGGLE_KEYS, FeatureToggles
from pyxeetb.tunables import TUNABLE_BOUNDS, TwitchTunables

log = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: str) -> bool:
    """For a toggle named explicitly in a partial (non-browser) POST. A bare
    HTML checkbox submits the literal string "on", so that has to count as
    true, but an explicit `alerts_enabled=false` from a script should mean
    what it says rather than "present, therefore on"."""
    return value.strip().lower() in _TRUTHY


def _parse_tunables(form: Mapping[str, Any]) -> tuple[dict[str, int], list[str]]:
    """Validate every submitted tunable against its bounds. Fields absent from
    the form are simply not part of the update."""
    submitted: dict[str, int] = {}
    errors: list[str] = []
    for name, (lo, hi) in TUNABLE_BOUNDS.items():
        raw = form.get(name)
        if raw is None:
            continue
        try:
            value = int(str(raw))
        except ValueError:
            errors.append(f"{name}: not a number")
            continue
        if value < lo or value > hi:
            errors.append(f"{name}: must be between {lo} and {hi}")
            continue
        submitted[name] = value
    return submitted, errors


def _live_status(ctx: AdminContext) -> LiveStatus:
    return LiveStatus(uptime_seconds=int(time.monotonic() - ctx.started_at))


async def _community_snapshot(ctx: AdminContext) -> dict[str, Any]:
    """Read-only dashboard data — management itself stays in chat (!addcom,
    etc.); this is just visibility so a mod doesn't need a second tool."""
    usage, usage_since = await ctx.db.command_usage()
    return {
        "top_points": await ctx.db.top_points(limit=5),
        "custom_commands": sorted(await ctx.db.list_commands()),
        "timers": await ctx.db.list_timers(),
        "blocked_term_count": len(await ctx.db.list_filter_values("term")),
        "allowed_domains": await ctx.db.list_filter_values("domain"),
        "quote_count": await ctx.db.quote_count(),
        "counters": [c.name for c in await ctx.db.load_counters()],
        "usage": usage,
        "usage_since": usage_since,
    }


async def _page_response(
    ctx: AdminContext,
    *,
    tunables: TwitchTunables | None = None,
    toggles: FeatureToggles | None = None,
    message: str | None = None,
    error: bool = False,
    status: int = 200,
) -> web.Response:
    html = render_settings_page(
        tunables=tunables or ctx.settings.tunables,
        toggles=toggles or ctx.settings.toggles,
        community=await _community_snapshot(ctx),
        broadcast_info=ctx.broadcast_info,
        status=_live_status(ctx),
        has_logo=ctx.logo is not None,
        message=message,
        error=error,
    )
    return protect(web.Response(text=html, content_type="text/html", status=status))


async def handle_settings_get(request: web.Request) -> web.Response:
    ctx = get_ctx(request)
    denied = authorize(ctx, request)
    if denied is not None:
        return denied
    return await _page_response(ctx)


async def handle_settings_post(request: web.Request) -> web.Response:
    ctx = get_ctx(request)
    denied = authorize(ctx, request)
    if denied is not None:
        return denied
    if not origin_ok(request):
        return protect(web.Response(status=403, text="Origin check failed — refusing to save."))
    form = await request.post()

    # Validate every tunable before writing anything, so one bad number can't
    # leave a 400 coming back after something already changed.
    submitted, errors = _parse_tunables(form)
    current = ctx.settings.tunables
    if errors:
        return await _page_response(
            ctx,
            tunables=TwitchTunables.from_dict({**current.to_dict(), **submitted}),
            message="Nothing was saved — " + "; ".join(errors),
            error=True,
            status=400,
        )

    # Absent-means-unchecked is right for this page's own form, but catastrophic
    # for a non-browser caller (curl, a Stream Deck script, allowed through by
    # origin_ok) — POSTing just `points_per_active_minute=2` would silently switch
    # off every toggle it didn't mention. FORM_MARKER is a hidden field only this
    # page's form carries, so a partial POST updates only the toggles it names.
    full_form = form.get(FORM_MARKER) is not None
    toggles = FeatureToggles.from_dict(ctx.settings.toggles.to_dict())
    for key in TOGGLE_KEYS:
        present = form.get(key) is not None
        if full_form:
            setattr(toggles, key, present)
        elif present:
            setattr(toggles, key, _is_truthy(str(form.get(key))))

    tunables = TwitchTunables.from_dict({**current.to_dict(), **submitted})
    await ctx.settings.replace(tunables=tunables, toggles=toggles)
    log.info(
        "Settings updated via /settings from %s: tunables=%s toggles=%s",
        client_ip(request),
        ctx.settings.tunables.to_overrides(),
        ctx.settings.toggles.to_overrides(),
    )
    return await _page_response(ctx, message="Saved.")
