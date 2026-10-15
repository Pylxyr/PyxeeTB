"""Access control for the gated /settings route.

There is no login page: /settings is reached one of two ways.

* Through the reverse proxy (Caddy), which does the signing in (`basic_auth`) and
  tells the bot who it let through in the X-Authenticated-User header. The header
  is only believed when the connection comes from a trusted proxy address, so
  nothing a client sends can fake it; the proxy overwrites it on every request.
* Directly on this machine (loopback, no proxy headers) — the streamer's own
  browser, or over an SSH tunnel. The Host header must name this machine, which
  stops a web page from reaching it through a DNS-rebinding trick.

Anything else is refused. Because a browser resends proxy credentials on its own,
saving a form is also checked for a matching Origin (see `origin_ok`) so another
site can't submit it from your logged-in browser.
"""

from __future__ import annotations

import logging

from aiohttp import web

from pyxeetb.admin.context import AdminContext, forwarded_host
from pyxeetb.admin.security import fetch_site_ok, origin_matches_host
from pyxeetb.netutil import host_without_port, is_loopback_host, is_trusted_peer, looks_proxied

log = logging.getLogger(__name__)

# Set by the proxy once it has authenticated the request (see deploy/Caddyfile).
AUTH_HEADER = "X-Authenticated-User"

PROTECTED_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

_LOCKED_MESSAGE = (
    "This page needs the reverse proxy's sign-in: this request came through a proxy that didn't "
    "vouch for it, or the server listens beyond localhost. Put Caddy's basic_auth in front of /settings "
    "(the README's \"Publishing with Caddy\" section), or open it directly on this machine."
)

_BAD_HOST_MESSAGE = (
    "Refusing this request: directly on this machine /settings only answers to localhost, 127.0.0.1 or [::1] "
    "(this stops a malicious web page from reaching it through a DNS-rebinding trick). Open it at "
    "http://localhost:<port>/settings."
)


def protect(response: web.Response) -> web.Response:
    for name, value in PROTECTED_HEADERS.items():
        response.headers[name] = value
    return response


def locked_response() -> web.Response:
    return protect(web.Response(status=403, text=_LOCKED_MESSAGE))


def _is_local(ctx: AdminContext, request: web.Request) -> bool:
    return not ctx.exposed and not looks_proxied(request.headers)


def authorize(ctx: AdminContext, request: web.Request) -> web.Response | None:
    """None to proceed; otherwise the response to return as-is."""
    if request.headers.get(AUTH_HEADER, "").strip() and is_trusted_peer(request.remote, ctx.trusted_proxies):
        return None
    if _is_local(ctx, request):
        # The Origin check compares against the Host header, which a DNS-rebinding
        # page controls, so direct access additionally insists the Host actually
        # names this machine.
        if not is_loopback_host(host_without_port(request.headers.get("Host"))):
            log.warning("Refused direct /settings request with Host %r.", request.headers.get("Host"))
            return protect(web.Response(status=403, text=_BAD_HOST_MESSAGE))
        return None
    return locked_response()


def origin_ok(request: web.Request) -> bool:
    ok = origin_matches_host(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        (request.headers.get("Host"), forwarded_host(request)),
    ) and fetch_site_ok(request.headers.get("Sec-Fetch-Site"))
    if not ok:
        log.warning(
            "Rejected %s %s from %s — Origin/Referer/Sec-Fetch-Site didn't match Host (possible CSRF, "
            "or a proxy that rewrites Host; nginx needs `proxy_set_header Host $host;`).",
            request.method,
            request.path,
            request.remote,
        )
    return ok
