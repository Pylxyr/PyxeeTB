"""End-to-end checks of the admin server's public and gated routes, run against a
real listener on an ephemeral port."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import aiohttp
from conftest import make_settings, run

from pyxeetb.admin.app import run_admin_server
from pyxeetb.admin.security import ConnectionLimiter
from pyxeetb.chatfeed import ChatFeed
from pyxeetb.netutil import host_without_port, parse_networks, rate_limit_key
from pyxeetb.runtime import RuntimeStatus


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager
async def _server(tmp_path, make_db):
    db = await make_db()
    port = _free_port()
    runner = await run_admin_server(
        chat_feed=ChatFeed(),
        status=RuntimeStatus(),
        settings=await make_settings(db),
        db=db,
        broadcast_info={},
        host="127.0.0.1",
        port=port,
        trusted_proxies=parse_networks("127.0.0.1/32")[0],
    )
    try:
        yield f"http://127.0.0.1:{port}", runner
    finally:
        await runner.cleanup()


def test_chat_json_and_healthz_are_rate_limited(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            statuses = [(await http.get(f"{base}/chat.json")).status for _ in range(125)]
            assert statuses[:120] == [200] * 120 and set(statuses[120:]) == {429}
            health = [(await http.get(f"{base}/healthz")).status for _ in range(32)]
            assert health[:30] == [200] * 30 and set(health[30:]) == {429}

    run(go())


def test_healthz_reuses_its_answer_for_a_few_seconds(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, runner), aiohttp.ClientSession() as http:
            ctx = next(iter(runner.app.values()))
            first = await (await http.get(f"{base}/healthz")).json()
            assert ctx.health_cache is not None
            second = await (await http.get(f"{base}/healthz")).json()
            assert first["uptime_seconds"] == second["uptime_seconds"]  # served from the cache

    run(go())


def test_websocket_connections_are_capped_per_client(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            sockets = [await http.ws_connect(f"{base}/ws/chat") for _ in range(8)]
            try:
                async with http.get(f"{base}/ws/chat") as refused:
                    assert refused.status == 429
                await sockets[0].close()
                await asyncio.sleep(0.2)  # the slot is released once the handler notices
                extra = await http.ws_connect(f"{base}/ws/chat")
                await extra.close()
            finally:
                for s in sockets:
                    await s.close()

    run(go())


def test_direct_settings_access_requires_a_loopback_host_header(tmp_path, make_db):
    """DNS rebinding: the attacker's page reaches us with Host: attacker.example, and an
    Origin that matches it, so only the Host itself can give it away."""

    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            ok = await http.get(f"{base}/settings", headers={"Accept": "text/html"})
            assert ok.status == 200
            rebound = await http.get(f"{base}/settings", headers={"Host": "attacker.example:8098"})
            assert rebound.status == 403
            origin = "http://attacker.example:8098"
            post = await http.post(
                f"{base}/settings",
                data={"action": "toggles"},
                headers={"Host": "attacker.example:8098", "Origin": origin},
            )
            assert post.status == 403

    run(go())


def test_settings_through_the_proxy_needs_the_proxys_sign_in(tmp_path, make_db):
    """Caddy's basic_auth sets X-Authenticated-User; a proxied request without it is refused."""

    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            proxied = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Host": "bot.example.com"}
            refused = await http.get(f"{base}/settings", headers=proxied)
            assert refused.status == 403
            signed_in = await http.get(f"{base}/settings", headers={**proxied, "X-Authenticated-User": "admin"})
            assert signed_in.status == 200

    run(go())


def test_saving_settings_through_the_proxy_checks_origin_and_stores_to_the_database(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, runner), aiohttp.ClientSession() as http:
            ctx = next(iter(runner.app.values()))
            headers = {
                "X-Forwarded-For": "203.0.113.9",
                "X-Forwarded-Host": "bot.example.com",
                "X-Authenticated-User": "admin",
            }
            form = {"gamble_max_bet": "123", "alerts_enabled": "on"}  # partial POST: only named toggles change
            cross_site = await http.post(
                f"{base}/settings", data=form, headers={**headers, "Origin": "https://evil.example"}
            )
            assert cross_site.status == 403 and ctx.settings.tunables.gamble_max_bet == 500
            ok = await http.post(
                f"{base}/settings", data=form, headers={**headers, "Origin": "https://bot.example.com"}
            )
            assert ok.status == 200
            assert ctx.settings.tunables.gamble_max_bet == 123 and ctx.settings.toggles.alerts_enabled
            assert await ctx.db.load_settings() == {"tunable.gamble_max_bet": "123", "toggle.alerts_enabled": "true"}
            bad = await http.post(f"{base}/settings", data={**form, "gamble_max_bet": "abc"}, headers={
                **headers, "Origin": "https://bot.example.com"})
            assert bad.status == 400 and ctx.settings.tunables.gamble_max_bet == 123  # nothing half-saved

    run(go())


def test_a_forged_sign_in_header_from_an_untrusted_address_is_ignored():
    from types import SimpleNamespace

    from pyxeetb.admin.handlers.auth import authorize

    ctx = SimpleNamespace(trusted_proxies=parse_networks("127.0.0.1/32")[0], exposed=True)
    request = SimpleNamespace(
        headers={"X-Authenticated-User": "admin", "Host": "bot.example.com"}, remote="198.51.100.7"
    )
    denied = authorize(ctx, request)  # type: ignore[arg-type]
    assert denied is not None and denied.status == 403


def test_rate_limit_key_groups_ipv6_by_64_and_leaves_ipv4_alone():
    assert rate_limit_key("203.0.113.9") == "203.0.113.9"
    a = rate_limit_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd")
    b = rate_limit_key("2001:db8:1:2:1111:2222:3333:4444")
    assert a == b == "2001:db8:1:2::/64"
    assert rate_limit_key("2001:db8:1:3::1") != a
    assert rate_limit_key("::ffff:203.0.113.9") == "203.0.113.9"


def test_host_without_port():
    assert host_without_port("localhost:8098") == "localhost"
    assert host_without_port("[::1]:8098") == "::1"
    assert host_without_port("127.0.0.1") == "127.0.0.1"
    assert host_without_port(None) == ""


def test_connection_limiter_counts_and_releases():
    lim = ConnectionLimiter(max_per_key=2, max_total=3)
    assert lim.acquire("a") and lim.acquire("a") and not lim.acquire("a")
    assert lim.acquire("b") and not lim.acquire("c")  # total cap
    lim.release("a")
    assert lim.acquire("c") and lim.total == 3
    lim.release("zzz")  # releasing something never acquired is a no-op
    assert lim.total == 3
