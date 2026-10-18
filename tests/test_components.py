"""Command-level tests: each component is built exactly as the bot wires it and driven
through its command callbacks with a fake context. This is what handing components
only the services they use buys — no twitchio connection, no monkeypatching."""

from types import SimpleNamespace

from conftest import run
from test_bot_wiring import _bot, _chatter, _component, _shutdown
from pyxeetb.components.custom_commands import CustomCommandsComponent
from pyxeetb.components.economy import EconomyComponent
from pyxeetb.components.queue import QueueComponent
from pyxeetb.components.quotes import QuotesComponent
from pyxeetb.components.timers import TimersComponent


class _Chat:
    """Calls a component's command and returns what the bot said."""

    def __init__(self, component):
        self.component = component
        self.said: list[str] = []

    def ctx(self, uid="1", name="Alice", **roles):
        async def reply(text):
            self.said.append(text)

        return SimpleNamespace(chatter=_chatter(uid, name, **roles), reply=reply)

    async def call(self, command, ctx, *args, **kwargs):
        await getattr(self.component, command).callback(self.component, ctx, *args, **kwargs)
        return self.said[-1]


def test_custom_command_management(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db, reserved_commands=frozenset({"sr"}))
        try:
            chat = _Chat(_component(bot, CustomCommandsComponent))
            mod = chat.ctx("9", "Owner", broadcaster=True)
            assert "Usage: !addcom" in await chat.call("add_command_cmd", mod, args="onlyname")
            assert "letters, numbers" in await chat.call("add_command_cmd", mod, args="bad-name hi")
            assert "already a command" in await chat.call("add_command_cmd", mod, args="points hi")  # a built-in
            assert "already a command" in await chat.call("add_command_cmd", mod, args="sr hi")  # another bot's
            assert "under" in await chat.call("add_command_cmd", mod, args="long " + "x" * 600)
            assert await chat.call("add_command_cmd", mod, args="hello Hi {user}!") == "Saved !hello."
            assert bot.custom.get("hello") is not None
            assert "100s cooldown" in await chat.call("command_options_cmd", mod, args="hello cd 100")
            assert "Usage: !comopt" in await chat.call("command_options_cmd", mod, args="hello role sub")  # roles are gone
            assert "Cooldown must be" in await chat.call("command_options_cmd", mod, args="hello cd forever")
            assert "No custom command !ghost" in await chat.call("command_options_cmd", mod, args="ghost cd 5")
            assert await chat.call("del_command_cmd", mod, name="hello") == "Removed !hello."
            assert "No custom command !hello" in await chat.call("del_command_cmd", mod, name="hello")
        finally:
            await _shutdown(bot)

    run(go())


def test_custom_command_management_is_guarded_to_the_broadcaster(tmp_path, make_db):
    """The tests above call callbacks directly, which skips guards — so check
    the guards themselves: a moderator (or anyone else) must fail them."""

    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            for name in ("addcom", "editcom", "delcom", "comopt"):
                command = bot.commands[name]
                assert command.guards, name
                broadcaster = SimpleNamespace(id="42")
                for chatter, allowed in ((SimpleNamespace(id="42"), True), (SimpleNamespace(id="7", moderator=True), False)):
                    ctx = SimpleNamespace(chatter=chatter, broadcaster=broadcaster)
                    results = [await _maybe_await(g(ctx)) for g in command.guards]
                    assert all(results) is allowed, (name, chatter)
        finally:
            await _shutdown(bot)

    run(go())


async def _maybe_await(value):
    return await value if hasattr(value, "__await__") else value


def test_quote_commands(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            chat = _Chat(_component(bot, QuotesComponent))
            mod, viewer = chat.ctx("9", "Mod", moderator=True), chat.ctx()
            assert "No quotes yet" in await chat.call("quote_cmd", viewer)
            assert "Usage: !addquote" in await chat.call("add_quote_cmd", mod, text="  ")
            assert await chat.call("add_quote_cmd", mod, text="never gonna give you up") == "Saved as #1."
            assert "never gonna give you up" in await chat.call("quote_cmd", viewer)
            assert "never gonna give you up" in await chat.call("quote_cmd", viewer, "1")
            assert "No quote #7" in await chat.call("quote_cmd", viewer, "7")
            assert "Usage: !quote" in await chat.call("quote_cmd", viewer, "abc")
            assert await chat.call("del_quote_cmd", mod, "1") == "Deleted #1."
            assert "Usage: !delquote" in await chat.call("del_quote_cmd", mod, "1")
        finally:
            await _shutdown(bot)

    run(go())


def test_queue_commands(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            chat = _Chat(_component(bot, QueueComponent))
            mod = chat.ctx("9", "Mod", moderator=True)
            alice, bob = chat.ctx("1", "Alice"), chat.ctx("2", "Bob")
            assert "isn't open" in await chat.call("queue_cmd", alice, args="join")
            assert "usage" in (await chat.call("queue_cmd", alice, args="open")).lower()  # viewers can't open it
            assert "open" in await chat.call("queue_cmd", mod, args="open")
            assert "#1" in await chat.call("queue_cmd", alice, args="join")
            assert "already #1" in await chat.call("queue_cmd", alice, args="join")
            assert "#2" in await chat.call("queue_cmd", bob, args="join")
            assert "Queue (2): Alice, Bob" in await chat.call("queue_cmd", alice, args="list")
            assert "#2 of 2" in await chat.call("queue_cmd", bob, args="")
            assert "Next up: Alice" in await chat.call("queue_cmd", mod, args="next")
            assert "You left" in await chat.call("queue_cmd", bob, args="leave")
            assert "not in the queue" in await chat.call("queue_cmd", bob, args="leave")
            assert "empty" in await chat.call("queue_cmd", mod, args="next")
            await chat.call("queue_cmd", mod, args="close")
            assert not bot.viewer_queue.open
        finally:
            await _shutdown(bot)

    run(go())


def test_timer_commands(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            chat = _Chat(_component(bot, TimersComponent))
            mod = chat.ctx("9", "Mod", moderator=True)
            assert "No timers yet" in await chat.call("timer_cmd", mod, args="list")
            assert "saved: every 10 min" in await chat.call("timer_cmd", mod, args="add social 10 Follow the channel!")
            assert "social (10m)" in await chat.call("timer_cmd", mod, args="list")
            assert "social is off" in await chat.call("timer_cmd", mod, args="off social")
            assert "social (10m, off)" in await chat.call("timer_cmd", mod, args="list")
            assert "needs 5 chat messages" in await chat.call("timer_cmd", mod, args="min social 5")
            assert "No timer named ghost" in await chat.call("timer_cmd", mod, args="on ghost")
            assert "Usage: !timer min" in await chat.call("timer_cmd", mod, args="min social many")
            assert "Removed timer social" in await chat.call("timer_cmd", mod, args="remove social")
            assert "No timer named social" in await chat.call("timer_cmd", mod, args="remove social")
        finally:
            await _shutdown(bot)

    run(go())


def test_economy_commands(tmp_path, make_db):
    async def go():
        bot = await _bot(tmp_path, make_db)
        try:
            chat = _Chat(_component(bot, EconomyComponent))
            alice = chat.ctx("1", "Alice")
            await bot.db.credit("2", "黒猫", 40, "kuroneko")
            assert "0 points" in await chat.call("points_cmd", alice)
            assert "40 points" in await chat.call("points_cmd", alice, "@kuroneko")  # by login
            assert "40 points" in await chat.call("points_cmd", alice, "黒猫")  # by display name
            assert "haven't seen" in await chat.call("points_cmd", alice, "nobody")
            assert "chat activity" in await chat.call("watchtime_cmd", alice)
            assert "Newcomer" in await chat.call("rank_cmd", alice)
            assert "Top points: 1. 黒猫 (40)" in await chat.call("leaderboard_cmd", alice)
            assert "Most chat time" not in await chat.call("leaderboard_cmd", alice, "")
            assert "Nobody's on the board" in await chat.call("leaderboard_cmd", alice, "watch")
            assert "claimed" in await chat.call("daily_cmd", alice)
            assert "already claimed" in await chat.call("daily_cmd", alice)
            assert "gave 10 points to 黒猫" in await chat.call("give_cmd", alice, "kuroneko", "10")
            assert "Usage" in await chat.call("give_cmd", alice, "", "")
            assert "turned off" in await chat.call("gamble_cmd", alice, "5")
        finally:
            await _shutdown(bot)

    run(go())
