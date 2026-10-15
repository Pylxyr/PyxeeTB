"""!quote formatting — pure functions; pyxeetb.db.Database owns storage."""

from __future__ import annotations

import datetime

from pyxeetb.db import Quote
from pyxeetb.textutil import parse_uint

MAX_QUOTE_LENGTH = 400


def format_quote(quote: Quote) -> str:
    when = datetime.datetime.fromtimestamp(quote.added_at, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
    return f'#{quote.id}: "{quote.text}" ({when})'


def parse_quote_id(raw: str) -> int | None:
    raw = raw.strip().lstrip("#")
    return parse_uint(raw)
