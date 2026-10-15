"""Assembles and starts the aiohttp application. `run_admin_server` is the
only public entry point; everything it serves lives in handlers/."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable

from aiohttp import web

from pyxeetb.admin.assets import preload_static, read_logo
from pyxeetb.admin.context import CTX_KEY, AdminContext, is_https
from pyxeetb.admin.handlers import live
from pyxeetb.admin.handlers import settings as settings_handlers
from pyxeetb.chatfeed import ChatFeed
from pyxeetb.db import Database
from pyxeetb.netutil import IPNetwork, is_loopback_host
from pyxeetb.runtime import RuntimeStatus
from pyxeetb.settings import LiveSettings

log = logging.getLogger(__name__)

_Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

_ROUTES: tuple[tuple[str, str, _Handler], ...] = (
    ("GET", "/healthz", live.handle_healthz),
    ("GET", "/chat-overlay", live.handle_chat_overlay),
    ("GET", "/chat.json", live.handle_chat),
    ("GET", "/ws/chat", live.handle_ws_chat),
    ("GET", "/logo.png", live.handle_logo),
    ("GET", "/commands", live.handle_commands_page),
    ("GET", "/settings", settings_handlers.handle_settings_get),
    ("POST", "/settings", settings_handlers.handle_settings_post),
)


@web.middleware
async def _security_headers_middleware(request: web.Request, handler: _Handler) -> web.StreamResponse:
    """Headers every response gets, app-wide, rather than threading them
    through each handler (/settings alone has several response sites).

    Strict-Transport-Security only sends over HTTPS (direct or via the
    reverse proxy); setdefault so a handler's own value isn't overridden.
    Referrer-Policy is deliberately not set: `no-referrer` makes browsers
    send `Origin: null` on same-origin form POSTs, which the CSRF check on
    /settings would then reject. A no-op for responses already
    prepared by their handler (WebSockets).
    """
    response = await handler(request)
    if is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


async def run_admin_server(
    *,
    chat_feed: ChatFeed,
    status: RuntimeStatus,
    settings: LiveSettings,
    db: Database,
    broadcast_info: dict[str, str],
    host: str,
    port: int,
    trusted_proxies: tuple[IPNetwork, ...],
) -> web.AppRunner:
    preload_static()

    exposed = not is_loopback_host(host)
    if exposed:
        log.warning(
            "The server listens on %s (reachable off this machine): /settings only answers requests "
            "that a trusted reverse proxy vouches for (X-Authenticated-User), never direct ones.",
            host,
        )

    commands_prefix = broadcast_info.get("Chat command prefix", "!")
    logo = read_logo("logo-96.png")
    ctx = AdminContext(
        chat_feed=chat_feed,
        settings=settings,
        db=db,
        status=status,
        broadcast_info=broadcast_info,
        logo=logo,
        logo_small=read_logo("logo-32.png"),
        commands_prefix=commands_prefix,
        has_logo=logo is not None,
        exposed=exposed,
        trusted_proxies=trusted_proxies,
    )

    app = web.Application(middlewares=[_security_headers_middleware])
    app[CTX_KEY] = ctx
    for method, path, handler in _ROUTES:
        # add_get (not add_route) so HEAD requests keep working on GET routes.
        (app.router.add_get if method == "GET" else app.router.add_post)(path, handler)

    runner = web.AppRunner(app)
    try:
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
    except BaseException:
        # e.g. the port is already taken: release what was acquired instead of
        # leaking a half-started app, without masking the original error.
        with contextlib.suppress(Exception):
            await runner.cleanup()
        raise
    log.info(
        "Admin server listening on http://%s:%d (/chat-overlay, /commands, /chat.json, /ws/chat, "
        "/healthz, /logo.png, /settings)",
        host,
        port,
    )
    return runner
