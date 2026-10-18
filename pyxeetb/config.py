from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from pyxeetb.emotes import PROVIDERS as EMOTE_PROVIDERS
from pyxeetb.fsutil import private_dir
from pyxeetb.netutil import DEFAULT_TRUSTED_PROXIES, IPNetwork, parse_networks
from pyxeetb.runtime import DEFAULT_REPLY_SUFFIXES

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

# Where !commands / !help send viewers by default: the static, built-in-commands-only
# GitHub Pages site that .github/workflows/pages.yml rebuilds on every push to main
# (the page lives at <base>/commands). Forks override it with TWITCH_PUBLIC_BASE_URL.
DEFAULT_PUBLIC_BASE_URL = "https://pylxyr.github.io/PyxeeTB"



def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        # print(), not log — this runs before configure_logging() exists.
        print(f"WARNING: {name}={raw!r} is not a valid integer — using {default}.")
        return default


_TRUE_TOKENS = {"1", "true", "yes", "on"}
_FALSE_TOKENS = {"0", "false", "no", "off"}


def _reply_suffixes_env(name: str) -> tuple[str, ...]:
    """Comma-separated suffixes rotated onto bot messages; unset = the default set, "none" = no suffix."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return DEFAULT_REPLY_SUFFIXES
    if raw.lower() in ("none", "off", "false", "0"):
        return ()
    return tuple(" " + token.strip() for token in raw.split(",") if token.strip())


def _command_names_env(name: str) -> frozenset[str]:
    """Comma-separated command names (with or without the prefix) another bot answers to."""
    return frozenset(t.strip().lstrip("!").lower() for t in os.getenv(name, "").split(",") if t.strip().lstrip("!"))


def _emote_providers_env(name: str) -> tuple[str, ...]:
    """Comma-separated third-party emote providers for the chat overlay.
    Unset = all of them (7tv, bttv, ffz); "none" turns third-party emotes off."""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return EMOTE_PROVIDERS
    if raw in ("none", "off", "false", "0"):
        return ()
    wanted = [t.strip() for t in raw.split(",") if t.strip()]
    unknown = [t for t in wanted if t not in EMOTE_PROVIDERS]
    if unknown:
        print(f"WARNING: {name} has unknown providers {', '.join(unknown)} — ignoring them (known: {', '.join(EMOTE_PROVIDERS)}).")
    return tuple(p for p in EMOTE_PROVIDERS if p in wanted)


def _public_base_url_env(name: str) -> str | None:
    """Base URL (no trailing slash) the public commands page is under; !commands
    links to `<base>/commands`. Unset = the GitHub Pages default, so no per-deploy
    .env edit is needed. "none" turns the link off (terse in-chat listing)."""
    raw = os.getenv(name, "").strip().rstrip("/")
    if not raw:
        return DEFAULT_PUBLIC_BASE_URL
    if raw.lower() in ("none", "off", "false", "0"):
        return None
    if not raw.startswith(("http://", "https://")):
        # print(), not log — this runs before configure_logging() exists.
        print(f"WARNING: {name}={raw!r} has no http(s):// scheme — using the default {DEFAULT_PUBLIC_BASE_URL}.")
        return DEFAULT_PUBLIC_BASE_URL
    if raw.startswith("http://"):
        print(f"WARNING: {name}={raw!r} uses http://, not https:// — this is the link every viewer gets from !commands.")
    return raw


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE_TOKENS:
        return True
    if raw in _FALSE_TOKENS:
        return False
    print(f"WARNING: {name}={raw!r} is not a recognized boolean — using {default}.")
    return default


def _clamped_int_env(name: str, default: int, lo: int, hi: int) -> int:
    value = _int_env(name, default)
    clamped = max(lo, min(hi, value))
    if clamped != value:
        print(f"WARNING: {name}={value} is outside the allowed range {lo}-{hi} — using {clamped}.")
    return clamped


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _log_level_env(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip().upper()
    if not raw:
        return default
    if raw not in _VALID_LOG_LEVELS:
        print(f"WARNING: {name}={raw!r} is not a valid log level — using {default}.")
        return default
    return raw


@dataclass(frozen=True, slots=True)
class Settings:
    # Twitch app credentials — from https://dev.twitch.tv/console/apps
    client_id: str
    client_secret: str
    bot_id: str
    owner_id: str
    prefix: str

    # Local HTTP surface — serves /chat-overlay, /commands, /settings
    http_host: str
    http_port: int
    trusted_proxies: tuple[IPNetwork, ...]
    # Base URL of the public commands page (no trailing slash); None = link disabled.
    public_base_url: str | None
    reply_suffixes: tuple[str, ...]
    reserved_commands: frozenset[str]
    emote_providers: tuple[str, ...]
    db_backup_keep: int
    backup_dir: Path

    # Persistence — everything lives under data/.
    token_path: Path
    db_path: Path

    # Logging (stdout only — journald keeps it)
    log_level: str


def load_settings() -> Settings:
    private_dir(DATA_DIR)

    def _required(name: str) -> str:
        value = os.getenv(name, "").strip()
        if not value:
            raise RuntimeError(f"{name} is not set — add it to .env before starting. See .env.example.")
        return value

    def _required_numeric_id(name: str) -> str:
        # Guards against e.g. TWITCH_BOT_ID pasted as "Twitch ID:1536026185"
        # instead of just the digits — Helix rejects that with a bare
        # "Bad Identifiers" error.
        value = _required(name)
        if not value.isdigit():
            raise RuntimeError(
                f"{name}={value!r} isn't a plain numeric Twitch user ID — digits only, no "
                f"username, no label. Look one up at "
                f"https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/"
            )
        return value

    client_id = _required("TWITCH_CLIENT_ID")
    client_secret = _required("TWITCH_CLIENT_SECRET")
    bot_id = _required_numeric_id("TWITCH_BOT_ID")
    owner_id = _required_numeric_id("TWITCH_OWNER_ID")

    http_host = (os.getenv("TWITCH_HTTP_HOST") or "127.0.0.1").strip() or "127.0.0.1"

    trusted_proxies, rejected_proxies = parse_networks(
        os.getenv("TWITCH_TRUSTED_PROXIES", "").strip() or DEFAULT_TRUSTED_PROXIES
    )
    if rejected_proxies:
        print(
            f"WARNING: TWITCH_TRUSTED_PROXIES has entries that aren't an IP or CIDR range, ignoring "
            f"them: {', '.join(rejected_proxies)}"
        )

    public_base_url = _public_base_url_env("TWITCH_PUBLIC_BASE_URL")

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        bot_id=bot_id,
        owner_id=owner_id,
        prefix=os.getenv("TWITCH_PREFIX", "!").strip() or "!",
        http_host=http_host,
        http_port=_clamped_int_env("TWITCH_HTTP_PORT", 8098, 1024, 65535),
        trusted_proxies=trusted_proxies,
        public_base_url=public_base_url,
        reply_suffixes=_reply_suffixes_env("TWITCH_REPLY_SUFFIXES"),
        reserved_commands=_command_names_env("TWITCH_RESERVED_COMMANDS"),
        emote_providers=_emote_providers_env("TWITCH_EMOTE_PROVIDERS"),
        db_backup_keep=_clamped_int_env("TWITCH_DB_BACKUP_KEEP", 7, 0, 90),
        backup_dir=DATA_DIR / "backups",
        token_path=DATA_DIR / "twitch_tokens.json",
        db_path=DATA_DIR / "community.db",
        log_level=_log_level_env("LOG_LEVEL", "INFO"),
    )
