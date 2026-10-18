import json
import re

from pyxeetb.commands_reference import COMMANDS
from pyxeetb.config import DEFAULT_PUBLIC_BASE_URL
from pyxeetb.pages import build_site


def _payload(html: str) -> list[dict]:
    match = re.search(r"window\.__COMMANDS__ = (\[.*?\]);\n", html, re.S)
    assert match
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_static_site_has_the_commands_page_at_the_expected_path(tmp_path):
    written = build_site(tmp_path)
    assert (tmp_path / "commands" / "index.html") in written
    assert (tmp_path / ".nojekyll").exists() and (tmp_path / "index.html").exists()
    html = (tmp_path / "commands" / "index.html").read_text(encoding="utf-8")
    # No absolute paths: Pages serves this under /PyxeeTB/, not at the domain root.
    assert 'href="/logo.png' not in html and 'src="/logo.png' not in html
    assert (tmp_path / "logo.png").exists() and 'src="../logo.png"' in html


def test_static_site_lists_exactly_the_public_built_in_commands(tmp_path):
    build_site(tmp_path)
    payload = _payload((tmp_path / "commands" / "index.html").read_text(encoding="utf-8"))
    assert {c["name"] for c in payload} == {c.name for c in COMMANDS if c.public}
    assert {"Counters", "Custom Commands"}.isdisjoint({c["category"] for c in payload})
    for hidden in ("addcom", "editcom", "comopt", "delcom"):
        assert hidden not in {c["name"] for c in payload}


def test_default_commands_url_is_the_pages_url():
    assert f"{DEFAULT_PUBLIC_BASE_URL}/commands" == "https://pylxyr.github.io/PyxeeTB/commands"
