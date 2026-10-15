"""Cheermote artwork for the chat overlay.

Twitch resolves its own emotes (global and subscriber) into structured message
fragments — see chatfeed.fragments_to_dicts. Cheermotes ("Cheer100") arrive as
their own fragment type too, but with no image, so their artwork is looked up
from Twitch's Bits API and swapped in here.

Everything is best-effort: if the lookup fails the cheermote simply shows as text,
and nothing in this module can stop a chat message from reaching the overlay.

Image URLs never come from chat. They come from Twitch's Bits API response,
are checked against a small host allowlist, and only https is accepted, so a
malformed response can't point the overlay's <img> tags at an arbitrary server.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

REFRESH_SECONDS = 30 * 60
RETRY_SECONDS = 2 * 60

# Cheermote artwork is served from Twitch's CloudFront distribution.
_CHEERMOTE_HOST_SUFFIXES = ("jtvnw.net", "cloudfront.net")
_HOST = re.compile(r"[a-z0-9.-]+")


@dataclass(frozen=True, slots=True)
class CheerTier:
    min_bits: int
    url: str
    color: str | None  # "#rrggbb"


def safe_image_url(url: object, suffixes: tuple[str, ...] = _CHEERMOTE_HOST_SUFFIXES) -> str | None:
    """`url` as an https URL if it points at an allowed image host, else None.
    Accepts protocol-relative ("//cdn...") and upgrades plain http; refuses
    userinfo, non-default ports, backslashes and control or non-ASCII
    characters outright rather than trusting two URL parsers to agree."""
    if not isinstance(url, str):
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if not url or len(url) > 400 or any(ord(ch) <= 0x20 or ord(ch) >= 0x7F or ch == "\\" for ch in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or "@" in parts.netloc or port not in (None, 443):
        return None
    host = parts.hostname or ""
    if not _HOST.fullmatch(host):
        return None
    if not any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
        return None
    return url


def parse_cheermotes(cheermotes: Iterable[Any]) -> dict[str, list[CheerTier]]:
    """Twitch's Bits cheermote list (TwitchIO `Cheermote` objects, read by
    attribute) -> {lowercase prefix: tiers sorted by min_bits}. Dark-background
    artwork is used since the overlay is dark; animated is preferred."""
    result: dict[str, list[CheerTier]] = {}
    for cheermote in cheermotes:
        prefix = str(getattr(cheermote, "prefix", "") or "").lower()
        if not prefix:
            continue
        tiers: list[CheerTier] = []
        for tier in getattr(cheermote, "tiers", None) or []:
            min_bits = getattr(tier, "min_bits", None)
            url = _cheer_image(getattr(tier, "images", None))
            if isinstance(min_bits, int) and url:
                tiers.append(CheerTier(min_bits, url, _cheer_color(getattr(tier, "colour", None))))
        if tiers:
            result[prefix] = sorted(tiers, key=lambda t: t.min_bits)
    return result


def _cheer_image(images: object) -> str | None:
    dark = images.get("dark") if isinstance(images, dict) else None
    if not isinstance(dark, dict):
        return None
    for image_format in ("animated", "static"):
        scales = dark.get(image_format)
        if isinstance(scales, dict):
            for scale in ("2", "1.5", "3", "1"):
                url = safe_image_url(scales.get(scale))
                if url:
                    return url
    return None


def _cheer_color(colour: object) -> str | None:
    code = getattr(colour, "code", None)
    return f"#{code:06x}" if isinstance(code, int) and 0 <= code <= 0xFFFFFF else None


CheermoteFetcher = Callable[[], Awaitable[Iterable[Any]]]


class CheermoteService:
    def __init__(self, fetcher: CheermoteFetcher) -> None:
        self._fetcher = fetcher
        self._cheermotes: dict[str, list[CheerTier]] = {}

    async def run(self) -> None:
        """Keeps the cheermote list fresh until cancelled."""
        while True:
            succeeded = await self.refresh()
            await asyncio.sleep(REFRESH_SECONDS if succeeded else RETRY_SECONDS)

    async def refresh(self) -> bool:
        """One lookup. On failure the previous list is kept; True if it loaded."""
        try:
            self._cheermotes = parse_cheermotes(await self._fetcher())
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Cheermotes: couldn't load (%s: %s) — keeping what was loaded before.", type(e).__name__, e)
            return False
        log.debug("Cheermotes loaded (%d).", len(self._cheermotes))
        return True

    def cheermote_tier(self, prefix: str, bits: int, tier: int) -> CheerTier | None:
        tiers = self._cheermotes.get(prefix.lower())
        if not tiers:
            return None
        for candidate in tiers:
            if candidate.min_bits == tier:
                return candidate
        eligible = [t for t in tiers if t.min_bits <= bits]
        return eligible[-1] if eligible else tiers[0]

    def decorate(self, fragments: list[dict[str, object]]) -> list[dict[str, object]]:
        """Turn the output of chatfeed.fragments_to_dicts into what the overlay
        renders: cheermote fragments get their artwork (or fall back to plain
        text when it isn't available). Everything else passes through."""
        out: list[dict[str, object]] = []

        def add_text(text: str) -> None:
            if out and out[-1]["type"] == "text":
                out[-1]["text"] = str(out[-1]["text"]) + text
            elif text:
                out.append({"type": "text", "text": text})

        for fragment in fragments:
            if fragment.get("type") != "cheermote":
                out.append(fragment)
                continue
            bits, tier_level = fragment.get("bits"), fragment.get("tier")
            tier = (
                self.cheermote_tier(str(fragment.get("prefix", "")), bits, tier_level)
                if isinstance(bits, int) and isinstance(tier_level, int)
                else None
            )
            if tier is None:
                add_text(str(fragment.get("name", "")))
            else:
                out.append({
                    "type": "cheermote",
                    "name": fragment.get("name", ""),
                    "url": tier.url,
                    "bits": bits,
                    "color": tier.color,
                })
        return out
