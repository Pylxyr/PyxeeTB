"""The public commands page: every public built-in command, organised into tabs.

Built from commands_reference.COMMANDS and the configured prefix. It shows every
public=True command exactly like chat's own !commands does, just with full
descriptions instead of a terse pipe-separated line.

Custom commands are owner-only and are never rendered here — this builder
doesn't even accept them. Counters are optional (the bot's own /commands route
passes them; the static GitHub Pages build never does).

The same builder produces the static page published to GitHub Pages
(pyxeetb/pages.py) and the bot's /commands route. No per-request input feeds
it. The data is embedded as JSON and rendered client-side as text rather than
markup (see commands.js's escapeHtml) as a second layer of defence.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape

from pyxeetb.admin.assets import static_text, template
from pyxeetb.commands_reference import CATEGORIES, COMMANDS
from pyxeetb.db import Counter

COUNTER_CATEGORY = "Counters"


def build_commands_page(
    prefix: str,
    *,
    has_logo: bool,
    counters: Sequence[Counter] = (),
    logo_src: str = "/logo.png",
    favicon_src: str = "/logo.png?s=32",
) -> str:
    payload = [
        {
            "name": c.name,
            "aliases": [f"{prefix}{a}" for a in c.aliases],
            "usage": c.usage_line(prefix),
            "description": c.description,
            "who": c.who,
            "group": c.group,
            "category": c.category,
        }
        for c in COMMANDS
        if c.public
    ]
    categories = list(CATEGORIES)
    if counters:
        categories.append(COUNTER_CATEGORY)
        for ctr in counters:
            who = "Anyone" if ctr.public else "Moderators"
            payload.append(
                {
                    "name": ctr.name,
                    "aliases": [],
                    "usage": f"{prefix}{ctr.name} / {prefix}{ctr.name}++ / {prefix}{ctr.name}--",
                    "description": f"Currently {ctr.value}. Viewing is open to anyone; adjusting needs: {who}.",
                    "who": "Anyone",
                    "group": "anyone",
                    "category": COUNTER_CATEGORY,
                }
            )
    # A literal "</script>" inside the JSON would end the inline script tag
    # early; escaping "</" is standard practice for inline JSON, not something
    # today's static command text actually contains.
    data_json = json.dumps(payload).replace("</", "<\\/")
    categories_json = json.dumps(categories)

    counts = {cat: sum(1 for c in payload if c["category"] == cat) for cat in categories}
    tabs_html = "".join(
        f'<button class="tab{" active" if i == 0 else ""}" data-cat="{escape(cat)}">'
        f'<span class="dot"></span>{escape(cat)}<span class="count">{counts[cat]}</span></button>'
        for i, cat in enumerate(categories)
    )
    logo = f'<img src="{escape(logo_src)}" alt="" onerror="this.remove()">' if has_logo else ""

    return template("commands.html").substitute(
        css=static_text("commands.css"),
        js=static_text("commands.js"),
        logo=logo,
        favicon=escape(favicon_src),
        prefix=escape(prefix),
        tabs_html=tabs_html,
        first_category=escape(categories[0]),
        first_category_lower=escape(categories[0].lower()),
        data_json=data_json,
        categories_json=categories_json,
    )
