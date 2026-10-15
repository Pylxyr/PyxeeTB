"""The shared state every admin handler reads.

Handlers are plain functions rather than methods on one large class; the state
they share lives here, is built once by run_admin_server(), and is fetched from
the aiohttp app with get_ctx(request).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aiohttp import web

from pyxeetb.admin.security import ConnectionLimiter, RequestRateLimiter
from pyxeetb.netutil import IPNetwork, is_trusted_peer, rate_limit_key, resolve_client_ip

if TYPE_CHECKING:
    from pyxeetb.chatfeed import ChatFeed
    from pyxeetb.db import Database
    from pyxeetb.runtime import RuntimeStatus
    from pyxeetb.settings import LiveSettings


@dataclass(slots=True)
class AdminContext:
    chat_feed: ChatFeed
    settings: LiveSettings
    db: Database
    status: RuntimeStatus
    broadcast_info: dict[str, str]
    # Read once at startup; None just means the pages render without a mark.
    logo: bytes | None
    logo_small: bytes | None
    # Built once at startup — see render/commands_page.py.
    commands_prefix: str
    has_logo: bool
    exposed: bool
    trusted_proxies: tuple[IPNetwork, ...]
    started_at: float = field(default_factory=time.monotonic)
    # 60/min per IP is generous for a human browsing a page of static text
    # while still capping a script against the one page advertised to a
    # channel's entire chat.
    commands_limiter: RequestRateLimiter = field(default_factory=lambda: RequestRateLimiter(60, 60.0))
    # (built_at monotonic, html) for the /commands page — see handlers/live.py.
    commands_cache: tuple[float, str] | None = None
    # The other unauthenticated routes. /chat.json is polled every couple of
    # seconds by an overlay whose socket is down, so its ceiling is higher than
    # the human-paced /commands; /healthz is for one uptime monitor.
    chat_limiter: RequestRateLimiter = field(default_factory=lambda: RequestRateLimiter(120, 60.0))
    health_limiter: RequestRateLimiter = field(default_factory=lambda: RequestRateLimiter(30, 60.0))
    # An OBS source plus a few browser tabs per client, and a hard ceiling overall.
    ws_limiter: ConnectionLimiter = field(default_factory=lambda: ConnectionLimiter(8, 100))
    # (built_at monotonic, body, http status) for /healthz — see handlers/live.py.
    health_cache: tuple[float, dict[str, object], int] | None = None


CTX_KEY = web.AppKey("admin_ctx", AdminContext)


def get_ctx(request: web.Request) -> AdminContext:
    return request.app[CTX_KEY]


def client_ip(request: web.Request) -> str:
    return resolve_client_ip(
        request.remote, request.headers.get("X-Forwarded-For"), get_ctx(request).trusted_proxies
    )


def rate_key(request: web.Request) -> str:
    """Per-client key for rate limits and lockouts (IPv6 grouped by /64)."""
    return rate_limit_key(client_ip(request))


def _trusted_header(request: web.Request, name: str) -> str | None:
    if not is_trusted_peer(request.remote, get_ctx(request).trusted_proxies):
        return None
    value = request.headers.get(name)
    return value.split(",")[0].strip() if value else None


def is_https(request: web.Request) -> bool:
    if request.secure:
        return True
    return (_trusted_header(request, "X-Forwarded-Proto") or "").lower() == "https"


def forwarded_host(request: web.Request) -> str | None:
    return _trusted_header(request, "X-Forwarded-Host")
