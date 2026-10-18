"""Covers the HTML-producing admin/render functions directly — no HTTP
server, no event loop needed, since they're plain functions over plain
data. Mostly presence/absence checks rather than exact-markup matches, so
these don't break on every minor styling tweak."""

from pyxeetb.admin.render.commands_page import build_commands_page
from pyxeetb.admin.render.settings_page import LiveStatus, render_settings_page
from pyxeetb.db import Counter, TimerRow
from pyxeetb.toggles import FeatureToggles
from pyxeetb.tunables import TwitchTunables


def _settings_html(**community_overrides):
    community = {"top_points": [], "custom_commands": []}
    community.update(community_overrides)
    return render_settings_page(
        tunables=TwitchTunables(),
        toggles=FeatureToggles(),
        community=community,
        broadcast_info={"Chat command prefix": "!"},
        status=LiveStatus(uptime_seconds=120),
        has_logo=False,
    )


def test_settings_page_renders_every_tunable_group():
    html = _settings_html()
    # "Points & rewards" is checked separately: & is HTML-escaped to &amp; in
    # the real output, so the literal string would never match (and
    # shouldn't — that's correct escaping, not a bug to work around twice).
    assert "Points &amp; rewards" in html
    for group in ("Gambling", "Chat filters", "Custom commands", "Viewer queue"):
        assert group in html
    assert "duel_max_bet" in html and "queue_max_size" in html


def test_settings_page_renders_every_toggle():
    html = _settings_html()
    for key in FeatureToggles().to_dict():
        assert key in html


def test_settings_page_shows_timers_counters_and_quotes_when_present():
    html = _settings_html(
        timers=[TimerRow("promo", "msg", 20, 5, True)],
        counters=["deaths", "wins"],
        quote_count=3,
        blocked_term_count=2,
        allowed_domains=["twitch.tv"],
    )
    assert "promo" in html and "deaths" in html and "wins" in html
    assert "3 quote(s) saved" in html
    assert "Blocked terms: 2" in html and "twitch.tv" in html


def test_settings_page_omits_empty_sections():
    html = _settings_html()
    assert "Timers:" not in html and "Counters:" not in html and "quote(s) saved" not in html


def test_settings_page_shows_a_banner_message():
    kwargs = dict(
        tunables=TwitchTunables(), toggles=FeatureToggles(),
        community={"top_points": [], "custom_commands": []}, broadcast_info={}, status=LiveStatus(0), has_logo=False,
    )
    ok_html = render_settings_page(**kwargs, message="Saved.", error=False)
    error_html = render_settings_page(**kwargs, message="Something went wrong.", error=True)
    assert "Saved." in ok_html and "Something went wrong." in error_html
    assert "banner-ok" in ok_html and "banner-error" in error_html


def test_commands_page_lists_every_built_in_category_and_no_custom_commands():
    html = build_commands_page("!", has_logo=False)
    for category in ("Points & Leaderboard", "Games & Fun", "Stream Info", "Moderator Tools"):
        assert category in html
    assert "Custom Commands" not in html


def test_commands_page_does_not_accept_or_show_custom_commands():
    import inspect

    assert "custom" not in inspect.signature(build_commands_page).parameters
    html = build_commands_page("!", has_logo=False)
    # The owner-only management commands are not advertised to viewers either.
    for hidden in ("!addcom", "!editcom", "!delcom", "!comopt"):
        assert hidden not in html, hidden


def test_commands_page_lists_counters_with_permission_hint():
    counters = [Counter(name="deaths", value=7, public=False), Counter(name="wins", value=2, public=True)]
    html = build_commands_page("!", has_logo=False, counters=counters)
    assert "Counters" in html and "!deaths" in html and "!wins++" in html
    assert "Currently 7" in html and "Currently 2" in html


def test_commands_page_without_counters_has_no_counters_category():
    html = build_commands_page("!", has_logo=False)
    assert "Counters" not in html


def test_settings_page_shows_command_usage():
    html = _settings_html(usage=[("points", 12, 0.0), ("8ball", 3, 0.0)], usage_since=1_700_000_000.0)
    assert "Command usage" in html and "!points" in html and ">12<" in html
    assert "Counting since 2023-11-14" in html
    assert "Not used yet" in html  # commands that never ran are listed too


def test_settings_page_without_usage_explains_itself():
    assert "No commands used yet" in _settings_html()
