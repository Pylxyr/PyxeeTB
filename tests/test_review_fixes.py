"""Regression tests for the issues found in the code review: each one failed
before its fix."""

import asyncio
import logging
import random
import sqlite3
from types import SimpleNamespace

from conftest import make_settings, run
from test_bot_wiring import _bot, _chatter, _component, _shutdown
from pyxeetb.cooldown import CooldownTracker
from pyxeetb.duels import DuelManager
from pyxeetb.economy import Economy
from pyxeetb.filters import TermMatcher, normalize_for_matching
from pyxeetb.giveaway import GiveawayManager
from pyxeetb.runtime import RuntimeStatus
from pyxeetb.toggles import FeatureToggles
from pyxeetb.tunables import TwitchTunables


async def _economy(tmp_path, make_db, **toggles):
    db = await make_db()
    settings = await make_settings(db)
    await settings.update(gamble_enabled=True, gamble_cooldown_seconds=30, gamble_max_bet=10, **toggles)

    async def live():
        return True

    return db, Economy(db, settings, RuntimeStatus(), is_live=live, rng=random.Random(1))


# -- cooldown race -----------------------------------------------------------

def test_concurrent_gambles_respect_the_cooldown(tmp_path, make_db):
    async def go():
        db, eco = await _economy(tmp_path, make_db)
        await db.credit("1", "Alice", 1000)
        replies = await asyncio.gather(*[eco.gamble("1", "Alice", "10") for _ in range(5)])
        assert sum("bet 10" in r for r in replies) == 1
        assert sum("cool down" in r for r in replies) == 4

    run(go())


def test_a_rejected_gamble_does_not_start_the_cooldown(tmp_path, make_db):
    async def go():
        db, eco = await _economy(tmp_path, make_db)
        await db.credit("1", "Alice", 1000)
        assert "Usage" in await eco.gamble("1", "Alice", "nonsense")
        assert "bet 10" in await eco.gamble("1", "Alice", "10")  # not on cooldown from the bad attempt

    run(go())


def test_concurrent_gives_respect_the_cooldown_and_failures_release_it(tmp_path, make_db):
    async def go():
        db, eco = await _economy(tmp_path, make_db)
        await db.credit("1", "Alice", 100)
        await db.credit("2", "Bob", 0, "bob")
        replies = await asyncio.gather(*[eco.give("1", "Alice", "bob", "5") for _ in range(4)])
        assert sum("gave 5" in r for r in replies) == 1
        assert (await db.get_stats("1"))["points"] == 95
        # an unknown target must not burn the sender's cooldown
        assert "haven't seen" in await eco.give("2", "Bob", "nobody", "1")
        await db.credit("2", "Bob", 10)
        assert "gave 1" in await eco.give("2", "Bob", "alice", "1")

    run(go())


def test_cooldown_clear_releases_a_reservation():
    cd = CooldownTracker()
    cd.mark("k")
    assert cd.remaining("k", 60) > 0
    cd.clear("k")
    assert cd.remaining("k", 60) == 0


# -- login lookup ------------------------------------------------------------

def test_viewers_can_be_found_by_login_even_with_a_localized_display_name(make_db):
    async def go():
        db = await make_db()
        await db.credit("2", "黒猫", 5, "KuroNeko")
        assert await db.find_by_name("kuroneko") == ("2", "黒猫")
        assert await db.find_by_name("黒猫") == ("2", "黒猫")

    run(go())


def test_login_match_beats_display_name_match(make_db):
    async def go():
        db = await make_db()
        await db.credit("1", "Sam", 1, "someoneelse")  # display name happens to be 'Sam'
        await db.credit("2", "Other", 1, "sam")  # login is 'sam'
        assert await db.find_by_name("sam") == ("2", "Other")

    run(go())


def test_award_tick_records_logins(tmp_path, make_db):
    async def go():
        db, eco = await _economy(tmp_path, make_db)
        from pyxeetb.chatevent import ChatEvent

        eco.note_activity(ChatEvent(user_id="7", login="Kuro", name="黒猫", text="hi"))
        await eco.award_tick()
        assert await db.find_by_name("kuro") == ("7", "黒猫")

    run(go())


def test_database_upgrades_from_schema_v3(tmp_path):
    path = tmp_path / "old.db"
    from pyxeetb import db as dbmod

    conn = sqlite3.connect(path)
    conn.executescript(dbmod._SCHEMA_V1)
    for version in (2, 3):
        for stmt in dbmod._MIGRATIONS[version]:
            conn.execute(stmt)
    conn.execute("PRAGMA user_version = 3")
    conn.execute("INSERT INTO viewer_stats (user_id, display_name, points, updated_at) VALUES ('1','Old',9,0)")
    conn.commit()
    conn.close()

    async def go():
        db = dbmod.Database(path)
        await db.connect()
        try:
            assert await db.schema_version() == dbmod.SCHEMA_VERSION >= 4
            assert (await db.get_stats("1"))["points"] == 9
            assert await db.find_by_name("old") == ("1", "Old")  # falls back to display name
        finally:
            await db.close()

    run(go())


# -- settings persistence ----------------------------------------------------

def test_only_non_default_values_are_saved():
    t = TwitchTunables.from_dict({"gamble_max_bet": 77})
    assert t.to_overrides() == {"gamble_max_bet": 77}
    assert TwitchTunables.from_dict({"gamble_max_bet": 500}).to_overrides() == {}  # equals the default
    g = FeatureToggles.from_dict({"gamble_enabled": True, "timers_enabled": True})
    assert g.to_overrides() == {"gamble_enabled": True}


def test_setlimit_and_toggle_persist_overrides_only(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.moderation import ModerationComponent

            component = _component(bot, ModerationComponent)

            async def reply(text):
                pass

            ctx = SimpleNamespace(chatter=_chatter("9", "Mod", moderator=True, broadcaster=True), reply=reply)
            await component.set_limit.callback(component, ctx, args="gamble_max_bet 77")
            await component.toggle.callback(component, ctx, args="gamble_enabled on")
            assert await bot.db.load_settings() == {"tunable.gamble_max_bet": "77", "toggle.gamble_enabled": "true"}
            assert bot.settings.tunables.gamble_max_bet == 77 and bot.settings.toggles.gamble_enabled
            await component.set_limit.callback(component, ctx, args="gamble_max_bet 500")  # back to default
            assert await bot.db.load_settings() == {"toggle.gamble_enabled": "true"}
        finally:
            await _shutdown(bot)

    run(go())


def test_a_bad_tunable_is_reported_once_not_on_every_read(caplog):
    from pyxeetb import tunables

    tunables._reported.clear()
    with caplog.at_level(logging.WARNING, logger="pyxeetb.tunables"):
        for _ in range(50):
            TwitchTunables.from_dict({"points_per_active_minute": 99999})
    assert len(caplog.records) == 1


# -- duels -------------------------------------------------------------------

def test_declining_an_expired_challenge_finds_nothing():
    now = [0.0]
    dm = DuelManager(SimpleNamespace(), clock=lambda: now[0])
    assert dm.challenge("a", "Alice", "b", 50, timeout_seconds=60) is None
    now[0] = 500.0
    assert dm.decline("b") is None


# -- giveaway ----------------------------------------------------------------

def test_reroll_draws_someone_new_until_entrants_run_out():
    gm = GiveawayManager(rng=random.Random(3))
    assert gm.reroll() is None  # nothing running
    gm.start("Prize", "mod")
    gm.enter("1", "Alice")
    gm.enter("2", "Bob")
    assert gm.reroll() is None  # nobody drawn yet
    first = gm.pick()
    second = gm.reroll()
    assert second and second != first and gm.current.winner == second
    assert gm.reroll() is None  # everyone has been drawn


def test_giveaway_command_reroll_and_mod_typos(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.giveaway import GiveawayComponent

            component = _component(bot, GiveawayComponent)
            replies = []

            async def reply(text):
                replies.append(text)

            mod = SimpleNamespace(chatter=_chatter("9", "Mod", moderator=True), reply=reply)
            viewer = SimpleNamespace(chatter=_chatter("1", "Alice"), reply=reply)
            cmd = component.giveaway_cmd.callback
            await cmd(component, mod, args="start Gift card")
            await cmd(component, mod, args="pck")  # typo: must not enter the mod
            assert "Usage" in replies[-1] and not bot.giveaway.has_entered("9")
            await cmd(component, viewer, args="")
            await cmd(component, mod, args="pick")
            await cmd(component, mod, args="pick")
            assert "already picked" in replies[-1] and "reroll" in replies[-1]
            await cmd(component, mod, args="reroll")
            assert "Nothing to re-roll" in replies[-1]  # only one entrant
        finally:
            await _shutdown(bot)

    run(go())


def test_giveaway_is_cleared_when_the_stream_goes_offline(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            bot.giveaway.start("Prize", "mod")
            bot.stream.set_live(True)
            await bot.event_stream_offline(SimpleNamespace())
            assert bot.giveaway.current is None
        finally:
            await _shutdown(bot)

    run(go())


# -- hype train --------------------------------------------------------------

def test_hype_train_level_ups_are_announced_once_each(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.alerts import AlertsComponent

            await bot.settings.update(alerts_enabled=True)
            sent = []

            async def announce(text):
                sent.append(text)

            bot.actions.announce = announce  # type: ignore[method-assign]
            comp = _component(bot, AlertsComponent)
            await comp.event_hype_train(SimpleNamespace(level=1, goal=500))
            # contributions inside level 1 (progress below goal) — nothing to say
            await comp.event_hype_train_progress(SimpleNamespace(level=1, progress=300, goal=500))
            # Twitch reports a level-up as a higher level with progress reset
            await comp.event_hype_train_progress(SimpleNamespace(level=2, progress=20, goal=800))
            await comp.event_hype_train_progress(SimpleNamespace(level=2, progress=200, goal=800))
            await comp.event_hype_train_progress(SimpleNamespace(level=3, progress=5, goal=1200))
            assert [s for s in sent if "reached level" in s] == [
                "\U0001f682 Hype Train reached level 2! \U0001f525",
                "\U0001f682 Hype Train reached level 3! \U0001f525",
            ]
            await comp.event_hype_train_end(SimpleNamespace(level=3, top_contributions=[]))
            await comp.event_hype_train(SimpleNamespace(level=1, goal=500))
            await comp.event_hype_train_progress(SimpleNamespace(level=2, progress=1, goal=800))
            assert sum("reached level 2" in s for s in sent) == 2  # a new train announces again
        finally:
            await _shutdown(bot)

    run(go())


# -- filters in other scripts -----------------------------------------------

def test_marks_that_are_part_of_the_word_are_kept_in_thai_japanese_and_hindi():
    assert normalize_for_matching("ไม้") != normalize_for_matching("ไม่")
    assert normalize_for_matching("がっこう") != normalize_for_matching("かっこう")
    assert normalize_for_matching("मा") != normalize_for_matching("मां")
    assert not TermMatcher(["ไม่"]).find("ไม้")
    assert TermMatcher(["ไม่"]).find("ผม ไม่ ชอบ")  # a real hit still matches


def test_decorative_marks_are_still_stripped_from_latin_greek_and_cyrillic():
    assert normalize_for_matching("ba\u0334\u0301d") == "bad"  # zalgo
    assert normalize_for_matching("café") == "cafe"
    assert normalize_for_matching("b\u0430d") == "bad"  # Cyrillic а homoglyph


def test_hype_train_without_a_begin_event_just_learns_the_level(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.alerts import AlertsComponent

            await bot.settings.update(alerts_enabled=True)
            sent = []

            async def announce(text):
                sent.append(text)

            bot.actions.announce = announce  # type: ignore[method-assign]
            comp = _component(bot, AlertsComponent)
            await comp.event_hype_train_progress(SimpleNamespace(level=1, progress=10, goal=500))
            assert sent == []  # joined mid-train: no bogus "reached level 1"
            await comp.event_hype_train_progress(SimpleNamespace(level=2, progress=1, goal=800))
            assert len(sent) == 1 and "level 2" in sent[0]
        finally:
            await _shutdown(bot)

    run(go())


def test_hype_train_begin_is_dispatched_under_the_name_the_component_listens_for():
    """twitchio names the event from the subscription type; a listener with another name never fires."""
    from twitchio import eventsub
    from twitchio.eventsub.subscriptions import _SUB_MAPPING

    from pyxeetb.components.alerts import AlertsComponent

    sub_types = {
        "hype_train": eventsub.HypeTrainBeginSubscription.type,
        "hype_train_progress": eventsub.HypeTrainProgressSubscription.type,
        "hype_train_end": eventsub.HypeTrainEndSubscription.type,
        "subscription_message": eventsub.ChannelSubscribeMessageSubscription.type,
        "subscription_gift": eventsub.ChannelSubscriptionGiftSubscription.type,
    }
    for listener, sub_type in sub_types.items():
        assert _SUB_MAPPING.get(sub_type, sub_type.removeprefix("channel.")).replace(".", "_") == listener
        assert hasattr(AlertsComponent, f"event_{listener}")


def test_resubs_and_gifted_subs_pay_and_announce(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            from pyxeetb.components.alerts import AlertsComponent

            await bot.settings.update(alerts_enabled=True)
            sent = []

            async def announce(text):
                sent.append(text)

            bot.actions.announce = announce  # type: ignore[method-assign]
            comp = _component(bot, AlertsComponent)
            user = SimpleNamespace(id=7, name="kuro", display_name="Kuro")
            await comp.event_subscription_message(
                SimpleNamespace(user=user, tier="1000", cumulative_months=6, streak_months=6, months=1, message=None)
            )
            assert "Kuro resubscribed (Tier 1) for 6 months" in sent[-1] and "+100 points" in sent[-1]
            await comp.event_subscription_gift(SimpleNamespace(user=user, tier="1000", total=3, anonymous=False))
            assert "Kuro gifted 3 Tier 1 subs" in sent[-1] and "+300 points" in sent[-1]
            await comp.event_subscription_gift(SimpleNamespace(user=user, tier="1000", total=500, anonymous=False))
            assert "+5000 points" in sent[-1]  # capped at 50 subs' worth
            await comp.event_subscription_gift(SimpleNamespace(user=None, tier="2000", total=1, anonymous=True))
            assert "An anonymous gifter gifted 1 Tier 2 sub!" in sent[-1] and "points" not in sent[-1]
            assert (await bot.db.get_stats("7"))["points"] == 100 + 300 + 5000
            # a gift recipient's own subscribe event must not double-announce or pay
            before = len(sent)
            await comp.event_subscription(SimpleNamespace(user=user, tier="1000", gift=True))
            assert len(sent) == before
        finally:
            await _shutdown(bot)

    run(go())
