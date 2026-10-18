from conftest import run
from pyxeetb.customcommands import CustomCommandStore, clean_name, render_response
from pyxeetb.timers import TimerScheduler, parse_add
from pyxeetb.db import TimerRow


def test_names():
    assert clean_name("!Discord") == "discord" and clean_name("a b") is None and clean_name("x" * 26) is None


def test_render_variables():
    out = render_response("{user} -> {touser} #{count} {args} @ {channel} {unknown}", user="A", args="@Bob hi", count=3, channel="C")
    assert out == "A -> Bob #3 @Bob hi @ C {unknown}"
    assert render_response("hey {touser}", user="A", args="", count=1, channel="C") == "hey A"


def test_store_execution_rules(make_db):
    async def go():
        db = await make_db()
        now = [0.0]
        store = CustomCommandStore(db, clock=lambda: now[0])
        await store.load()
        await store.save("hi", "Hello {user}! ({count})", "1")
        kw = dict(user="Al", args="", channel="C", default_cooldown=3, owner=True)
        assert await store.execute("hi", **kw) == "Hello Al! (1)"
        assert await store.execute("hi", **kw) is None  # cooling down, silently
        now[0] = 4
        assert await store.execute("hi", **kw) == "Hello Al! (2)"
        assert await store.execute("missing", **kw) is None
        await store.set_option("hi", cooldown_seconds=0)
        assert await store.execute("hi", **kw) and await store.execute("hi", **kw)
        assert (await db.load_commands())[0].uses >= 4
        assert await store.delete("hi") and store.get("hi") is None

    run(go())


def test_only_the_owner_can_run_a_custom_command(make_db):
    async def go():
        db = await make_db()
        store = CustomCommandStore(db)
        await store.load()
        await store.save("hi", "Hello {user}!", "1")
        kw = dict(user="Al", args="", channel="C", default_cooldown=0)
        # A viewer, a moderator, a VIP or a subscriber all get silence — no reply, no error.
        assert await store.execute("hi", owner=False, **kw) is None
        assert store.get("hi").uses == 0  # and it doesn't count as a use
        assert await store.execute("hi", owner=True, **kw) == "Hello Al!"

    run(go())


def test_parse_timer_add():
    assert parse_add("promo 10 Follow the stream!") == ("promo", 10, "Follow the stream!")
    assert isinstance(parse_add("promo 1 too fast"), str)
    assert isinstance(parse_add("promo x hello"), str)
    assert isinstance(parse_add("bad name 10 hello"), str)
    assert isinstance(parse_add("promo 10"), str)


def test_timer_scheduler_baseline_interval_and_activity():
    sched = TimerScheduler()
    timers = [TimerRow("a", "m", 10, 5), TimerRow("off", "m", 10, 0, False)]
    assert sched.due(timers, now=0, total_messages=0) == []  # first sighting only sets the baseline
    assert sched.due(timers, now=600, total_messages=2) == []  # interval passed, room too quiet
    assert [t.name for t in sched.due(timers, now=601, total_messages=5)] == ["a"]
    assert sched.due(timers, now=602, total_messages=50) == []  # interval restarts after firing
    assert [t.name for t in sched.due(timers, now=1300, total_messages=60)] == ["a"]
    sched.reset()
    assert sched.due(timers, now=5000, total_messages=999) == []  # offline pause forgets baselines
