from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from pyxeetb.admin.app import run_admin_server
from pyxeetb.chatbot import TwitchChatBot
from pyxeetb.chatfeed import ChatFeed
from pyxeetb.config import Settings, load_settings
from pyxeetb.db import Database
from pyxeetb.legacy import import_legacy_state
from pyxeetb.maintenance import backup_loop
from pyxeetb.runtime import RuntimeStatus
from pyxeetb.settings import LiveSettings

_bg_tasks: set[asyncio.Task[object]] = set()


def configure_logging(settings: Settings) -> None:
    # stdout only: under systemd journald keeps (and rotates) it — `journalctl -u pyxeetb`.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    logging.getLogger("twitchio").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def _async_run(settings: Settings) -> None:
    configure_logging(settings)
    log = logging.getLogger(__name__)

    db = Database(settings.db_path)
    await db.connect()
    # Shared between the chat bot (appends every non-bot message — see
    # chatbot.py's _process_chat) and the admin server (/chat-overlay,
    # /chat.json, /ws/chat).
    chat_feed = ChatFeed()
    status = RuntimeStatus()

    # Runtime settings live in the database; the first start after upgrading from
    # the JSON-file era imports whatever those files held (and retires them).
    live_settings = LiveSettings(db)
    await live_settings.load()
    await import_legacy_state(db, live_settings, settings.db_path.parent)

    # Nested try/finally per resource (not one big try around just the chat
    # bot) so a failure acquiring a *later* resource still tears down
    # everything already acquired.
    try:
        admin_runner = await run_admin_server(
            chat_feed=chat_feed,
            status=status,
            settings=live_settings,
            db=db,
            broadcast_info={
                "Chat overlay": "/chat-overlay",
                "Chat command prefix": settings.prefix,
            },
            host=settings.http_host,
            port=settings.http_port,
            trusted_proxies=settings.trusted_proxies,
        )
        try:
            bot = TwitchChatBot(
                client_id=settings.client_id,
                client_secret=settings.client_secret,
                bot_id=settings.bot_id,
                owner_id=settings.owner_id,
                prefix=settings.prefix,
                chat_feed=chat_feed,
                settings=live_settings,
                db=db,
                token_storage_path=settings.token_path,
                public_base_url=settings.public_base_url,
                status=status,
                reply_suffixes=settings.reply_suffixes,
                reserved_commands=settings.reserved_commands,
            )
            if settings.db_backup_keep > 0:
                backup_task = asyncio.create_task(
                    backup_loop(db, settings.backup_dir, settings.db_backup_keep), name="db-backup"
                )
                _bg_tasks.add(backup_task)
                backup_task.add_done_callback(_bg_tasks.discard)

            loop = asyncio.get_running_loop()

            shutting_down = False

            def _handle_shutdown_signal(signum: int) -> None:
                # systemd sends SIGTERM and an impatient operator adds
                # Ctrl-C — without this guard, both would spawn their own
                # bot.close() and race over the same teardown.
                nonlocal shutting_down
                if shutting_down:
                    log.info("%s received — shutdown already in progress.", signal.Signals(signum).name)
                    return
                shutting_down = True
                log.info("%s received — initiating graceful shutdown.", signal.Signals(signum).name)
                task = asyncio.create_task(bot.close())
                _bg_tasks.add(task)
                task.add_done_callback(_bg_tasks.discard)

            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, _handle_shutdown_signal, sig)

            async with bot:
                await bot.start()
        finally:
            await admin_runner.cleanup()
    finally:
        # Reverse of setup order: the HTTP surface is already down (inner
        # finally above), so nothing can still be serving a request against
        # the database — see TwitchChatBot.close()'s docstring for why it
        # doesn't close the database itself.
        await db.close()


def _load_settings_or_exit() -> Settings:
    import sys

    try:
        return load_settings()
    except RuntimeError as exc:
        sys.exit(f"Config check FAILED: {exc}")


def run() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="pyxeetb")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate .env and exit — doesn't start the bot or touch Twitch.",
    )
    args = parser.parse_args()

    if args.check_config:
        sys.exit(_check_config())
    asyncio.run(_async_run(_load_settings_or_exit()))


def _check_config() -> int:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"Config check FAILED: {exc}")
        return 1

    # Deliberately never prints client_secret.
    print("Config OK:")
    print(f"  Twitch: bot_id={settings.bot_id} owner_id={settings.owner_id} prefix={settings.prefix!r}")
    print(
        f"  HTTP: http://{settings.http_host}:{settings.http_port} "
        "(/settings: open directly on this machine, or through a proxy that signs you in — see the README)"
    )
    print(f"  Trusted proxies: {', '.join(str(net) for net in settings.trusted_proxies) or 'none'}")
    if settings.public_base_url:
        print(f"  Public commands page: {settings.public_base_url}/commands (linked from !commands in chat)")
    else:
        print("  Public commands page: not configured (TWITCH_PUBLIC_BASE_URL unset) — !commands uses the in-chat listing")
    token_status = "found" if settings.token_path.exists() else "missing — run OAuth setup before starting"
    print(f"  Token file: {settings.token_path} ({token_status})")
    print(f"  Community DB: {settings.db_path}")
    return 0
