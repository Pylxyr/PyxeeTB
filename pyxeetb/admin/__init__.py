"""HTTP surface of the bot: the OBS chat overlay, the public commands page, and
the proxy-gated /settings page.

Layout:
    app.py        builds the aiohttp app (routes, middleware) — the only entry
                  point, `run_admin_server`, lives here
    context.py    the shared dependencies every handler reads, plus the
                  per-request helpers that need them (client address, HTTPS)
    handlers/     request handlers, grouped by concern (live data, media,
                  the gated settings routes and their access check)
    render/       pure functions that build the /settings and /commands HTML
    security.py   CSRF, rate-limit and URL-allowlist rules (stdlib only)
    assets.py     loads static/ (overlay pages, CSS, JS, HTML templates) and the logo
    static/       the front-end files themselves

There is no login code here on purpose: signing in to /settings is the reverse
proxy's job (Caddy basic_auth — see deploy/Caddyfile and handlers/auth.py).

Nothing is imported here on purpose: `from pyxeetb.admin.app import
run_admin_server` pulls in aiohttp, while security.py and render/ stay importable
without it.
"""
