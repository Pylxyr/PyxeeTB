"""Tests for the pieces split out of the old TwitchChatBot: reply decorator, stream
state, command throttle/usage, runtime settings, legacy import, broadcaster-only
settings, cheermotes."""

import datetime
import json
from types import SimpleNamespace

from conftest import make_settings, run
from test_bot_wiring import _bot, _chatter, _component, _shutdown
from pyxeetb.actions import ReplyDecorator
from pyxeetb.cheermotes import CheermoteService, safe_image_url
from pyxeetb.legacy import import_legacy_state
from pyxeetb.runtime import RuntimeStatus
from pyxeetb.settings import LiveSettings
from pyxeetb.streamstate import Reading, StreamState
from pyxeetb.throttle import CommandThrottle, UsageCounter


# -- reply decorator -----------------------------------------------------------

def test_replies_go_out_clean_unless_they_would_repeat():
    now = [0.0]
    d = ReplyDecorator((" A", " B"), clock=lambda: now[0])
    assert d.decorate("hello") == "hello"
    assert d.decorate("other") == "other"
    assert d.decorate("hello") == "hello A"  # a repeat inside the window gets a suffix
    assert d.decorate("hello") == "hello B"  # and the next repeat a different one
    now[0] = 500.0  # long ago: no longer a repeat
    assert d.decorate("hello") == "hello"


def test_decorator_truncates_to_twitchs_limit_even_with_a_suffix():
    d = ReplyDecorator((" \u2728",))
    assert len(d.decorate("x" * 900)) == 500
    again = d.decorate("x" * 900)
    assert len(again) == 500 and again.endswith("\u2728")


# -- stream state ---------------------------------------------------------------

def _stream(live=True, subscribed=True, started=None, title="T", game="G"):
    calls = []
    now = [0.0]
    status = RuntimeStatus()
    if subscribed:
        status.alert_subscriptions.update(stream_online=True, stream_offline=True, channel_update=True)

    async def fetch():
        calls.append(1)
        return Reading(live, started, title, game)

    started_sessions = []
    state = StreamState(status, fetch, on_live_start=lambda: started_sessions.append(1), clock=lambda: now[0])
    return state, calls, now, status, started_sessions


def test_eventsub_feeds_the_state_without_any_api_call():
    async def go():
        state, calls, now, status, sessions = _stream()
        began = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=90)
        assert state.set_live(True, began) is False  # first reading: not a flip
        assert sessions == [1]  # but a new live session starts
        state.apply_channel_update("New title", "Chatting")
        assert await state.is_live() is True
        assert await state.channel_info() == ("New title", "Chatting")
        uptime = await state.uptime()
        assert uptime is not None and 89 * 60 < uptime.total_seconds() < 91 * 60
        assert calls == []  # everything came from events
        assert state.set_live(False) is True
        assert await state.uptime() is None and calls == []

    run(go())


def test_polling_fills_the_gaps_and_a_failed_lookup_keeps_the_last_answer():
    async def go():
        state, calls, now, status, _ = _stream(live=True, subscribed=False, started=datetime.datetime.now(datetime.timezone.utc))
        assert await state.is_live() is True and len(calls) == 1
        assert await state.is_live() is True and len(calls) == 1  # cached
        now[0] = 200.0  # past the polling TTL
        assert await state.is_live() is True and len(calls) == 2
        assert await state.channel_info() == ("T", "G")

        async def broken():
            raise RuntimeError("helix down")

        state._fetch = broken  # type: ignore[assignment]
        now[0] = 400.0
        assert await state.is_live() is True  # last known answer, not a zeroed-out stream
        fresh = StreamState(RuntimeStatus(), broken, clock=lambda: 0.0)
        assert await fresh.is_live() is True  # unknown + failing: assume live
        assert await fresh.channel_info() is None

    run(go())


# -- throttle and usage ------------------------------------------------------------

def test_throttle_is_per_user_and_per_channel_and_exempts_moderators():
    now = [0.0]
    t = CommandThrottle(clock=lambda: now[0])
    assert t.allow("points", "1")
    assert not t.allow("points", "1")  # same user again
    assert not t.allow("points", "2")  # channel-wide 2s gap
    now[0] = 2.5
    assert t.allow("points", "2")  # different user once the channel gap has passed
    assert not t.allow("points", "1")  # but user 1 is still inside its own 5s
    assert t.allow("points", "1", exempt=True)  # moderators never wait
    assert t.allow("points", "1", exempt=True)
    assert t.allow("quote", "1")  # each command has its own clock
    now[0] = 100.0
    assert t.allow("followage", "1") and not t.allow("followage", "1")
    now[0] = 110.0
    assert not t.allow("followage", "1")  # followage's longer leash (15s)
    now[0] = 116.0
    assert t.allow("followage", "1")


def test_usage_counts_are_buffered_flushed_and_kept_on_failure(make_db):
    async def go():
        db = await make_db()
        u = UsageCounter()
        for name in ("points", "points", "8ball"):
            u.record(name)
        await u.flush(db)
        await u.flush(db)  # nothing pending: no-op
        usage, since = await db.command_usage()
        assert [(n, c) for n, c, _ in usage] == [("points", 2), ("8ball", 1)] and since is not None
        u.record("points")

        class Broken:
            async def add_command_usage(self, counts):
                raise RuntimeError("disk full")

        await u.flush(Broken())  # type: ignore[arg-type]
        await u.flush(db)  # the count survived the failed flush
        assert dict((n, c) for n, c, _ in (await db.command_usage())[0])["points"] == 3

    run(go())


def test_global_guard_throttles_viewers_and_counts_only_commands_that_ran(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            cmd = SimpleNamespace(name="points")
            viewer = SimpleNamespace(chatter=_chatter("1", "Alice"), command=cmd)
            other = SimpleNamespace(chatter=_chatter("2", "Bob"), command=cmd)
            mod = SimpleNamespace(chatter=_chatter("9", "Mod", moderator=True), command=cmd)
            assert await bot.global_guard(viewer) is True
            assert await bot.global_guard(viewer) is False  # spam: silently refused
            assert await bot.global_guard(other) is False  # inside the channel-wide gap
            assert await bot.global_guard(mod) is True and await bot.global_guard(mod) is True
            await bot.after_invoke(viewer)
            await bot.after_invoke(mod)
            await bot.usage.flush(bot.db)
            assert [(n, c) for n, c, _ in (await bot.db.command_usage())[0]] == [("points", 2)]
        finally:
            await _shutdown(bot)

    run(go())


# -- settings ----------------------------------------------------------------------

def test_settings_survive_a_restart_and_only_overrides_are_stored(make_db):
    async def go():
        db = await make_db()
        s = await make_settings(db)
        assert s.tunables.gamble_max_bet == 500 and not s.toggles.gamble_enabled
        await s.update(gamble_max_bet=99, gamble_enabled=True, timers_enabled=False)
        assert await db.load_settings() == {
            "tunable.gamble_max_bet": "99", "toggle.gamble_enabled": "true", "toggle.timers_enabled": "false",
        }
        again = LiveSettings(db)
        await again.load()
        assert again.tunables.gamble_max_bet == 99 and again.toggles.gamble_enabled and not again.toggles.timers_enabled
        await again.update(gamble_max_bet=500)  # back to the default -> stored as absence
        assert "tunable.gamble_max_bet" not in await db.load_settings()

    run(go())


def test_unknown_or_unreadable_stored_settings_are_ignored(make_db):
    async def go():
        db = await make_db()
        await db.write_settings({"tunable.gamble_max_bet": "not json", "tunable.nonsense": "5", "toggle.alerts_enabled": "true"})
        s = await make_settings(db)
        assert s.tunables.gamble_max_bet == 500 and s.toggles.alerts_enabled

    run(go())


# -- one-time import of the old JSON state --------------------------------------------

def test_legacy_files_are_imported_once_and_retired(tmp_path, make_db):
    async def go():
        db = await make_db()
        s = await make_settings(db)
        (tmp_path / "tunables.json").write_text(json.dumps({"gamble_max_bet": 250, "points_per_active_minute": 3}))
        (tmp_path / "toggles.json").write_text(json.dumps({"alerts_enabled": True, "timers_enabled": True}))
        (tmp_path / "specs.json").write_text(json.dumps({"cpu": "Ryzen 7", "gpu": "RTX 4070", "mouse": "Model O"}))
        done = await import_legacy_state(db, s, tmp_path)
        assert len(done) == 4
        assert s.tunables.gamble_max_bet == 250 and s.toggles.alerts_enabled
        commands = {c.name: c.response for c in await db.load_commands()}
        assert commands["specs"] == "CPU: Ryzen 7 | GPU: RTX 4070"
        assert commands["peripherals"] == "Mouse: Model O"
        assert not (tmp_path / "tunables.json").exists() and (tmp_path / "tunables.json.migrated").exists()
        assert await import_legacy_state(db, s, tmp_path) == []  # nothing left to import

    run(go())


def test_legacy_import_does_not_overwrite_an_existing_command(tmp_path, make_db):
    async def go():
        db = await make_db()
        s = await make_settings(db)
        await db.set_command("specs", "my own text", "1")
        (tmp_path / "specs.json").write_text(json.dumps({"cpu": "Ryzen 7"}))
        await import_legacy_state(db, s, tmp_path)
        assert {c.name: c.response for c in await db.load_commands()}["specs"] == "my own text"

    run(go())


# -- broadcaster-only settings --------------------------------------------------------

def test_economy_and_filter_actions_are_broadcaster_only_but_readable_by_mods(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.moderation import ModerationComponent

            comp = _component(bot, ModerationComponent)
            said = []

            async def reply(text):
                said.append(text)

            mod = SimpleNamespace(chatter=_chatter("9", "Mod", moderator=True), reply=reply)
            owner = SimpleNamespace(chatter=_chatter("1", "Owner", moderator=True, broadcaster=True), reply=reply)

            await comp.set_limit.callback(comp, mod, args="gamble_max_bet 5")
            assert "Only the broadcaster" in said[-1] and bot.settings.tunables.gamble_max_bet == 500
            await comp.set_limit.callback(comp, mod, args="gamble_max_bet")  # reading is fine
            assert "gamble_max_bet = 500" in said[-1]
            await comp.toggle.callback(comp, mod, args="filter_timeout_enabled on")
            assert "Only the broadcaster" in said[-1] and not bot.settings.toggles.filter_timeout_enabled
            # everything else stays a moderator's call
            await comp.set_limit.callback(comp, mod, args="permit_default_seconds 120")
            assert bot.settings.tunables.permit_default_seconds == 120
            await comp.toggle.callback(comp, mod, args="link_filter_enabled on")
            assert bot.settings.toggles.link_filter_enabled
            # and the broadcaster can change the guarded ones
            await comp.set_limit.callback(comp, owner, args="gamble_max_bet 5")
            await comp.toggle.callback(comp, owner, args="filter_timeout_enabled on")
            assert bot.settings.tunables.gamble_max_bet == 5 and bot.settings.toggles.filter_timeout_enabled
        finally:
            await _shutdown(bot)

    run(go())


# -- stream-info commands answer from the cache ----------------------------------------

def test_uptime_title_and_game_use_the_cache_not_the_api(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.stream_info import StreamInfoComponent

            comp = _component(bot, StreamInfoComponent)
            said = []

            async def reply(text):
                said.append(text)

            ctx = SimpleNamespace(chatter=_chatter(), reply=reply)
            bot.status.alert_subscriptions.update(stream_online=True, stream_offline=True, channel_update=True)
            began = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2, minutes=5)
            bot.stream.set_live(True, began)
            bot.stream.apply_channel_update("Speedrun night", "Celeste")
            await comp.uptime_cmd.callback(comp, ctx)
            await comp.title_cmd.callback(comp, ctx)
            await comp.game_cmd.callback(comp, ctx)
            assert "Live for 2h 5m" in said[0] and "Speedrun night" in said[1] and "Celeste" in said[2]
            bot.stream.set_live(False)
            await comp.uptime_cmd.callback(comp, ctx)
            assert "Not live" in said[-1]
        finally:
            await _shutdown(bot)

    run(go())


# -- cheermotes -------------------------------------------------------------------------

def test_cheermote_artwork_replaces_the_bare_fragment_and_falls_back_to_text():
    async def go():
        tier = SimpleNamespace(
            min_bits=100,
            images={"dark": {"static": {"2": "https://d3aqoihi2n8ty8.cloudfront.net/x/2.png"}}},
            colour=SimpleNamespace(code=0x9C3EE8),
        )

        async def fetch():
            return [SimpleNamespace(prefix="Cheer", tiers=[tier])]

        service = CheermoteService(fetch)
        frags = [{"type": "text", "text": "gg "}, {"type": "cheermote", "name": "Cheer100", "prefix": "Cheer", "bits": 100, "tier": 100}]
        assert service.decorate(frags) == [{"type": "text", "text": "gg Cheer100"}]  # nothing loaded yet: plain text
        assert await service.refresh() is True
        out = service.decorate(frags)
        assert out[1]["type"] == "cheermote" and out[1]["url"].startswith("https://") and out[1]["color"] == "#9c3ee8"

        async def broken():
            raise RuntimeError("bits api down")

        service._fetcher = broken  # type: ignore[assignment]
        assert await service.refresh() is False and service.decorate(frags)[1]["type"] == "cheermote"  # kept

    run(go())


def test_image_urls_must_be_https_on_an_allowed_host():
    assert safe_image_url("//static-cdn.jtvnw.net/x.png") == "https://static-cdn.jtvnw.net/x.png"
    for bad in ("https://evil.example/x.png", "https://jtvnw.net.evil.example/x.png", "https://user@jtvnw.net/x.png",
                "https://jtvnw.net:8443/x.png", "javascript:alert(1)", None):
        assert safe_image_url(bad) is None
