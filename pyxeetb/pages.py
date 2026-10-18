"""Builds the static public commands site published to GitHub Pages.

    python -m pyxeetb.pages <output-dir> [--prefix !]

Writes, under <output-dir>:

    commands/index.html   the built-in commands page   -> /PyxeeTB/commands
    index.html            redirects to commands/
    logo.png              the bot mark (page logo and favicon)
    .nojekyll             Pages serves the files as they are

It uses the same builder as the bot's own /commands route (public=True entries
of commands_reference.COMMANDS only), but with nothing dynamic: no counters and,
by construction, no custom commands — those are owner-only and never public.
The .github/workflows/pages.yml workflow runs this on every push to main.
"""

from __future__ import annotations

import argparse
import shutil
from html import escape
from pathlib import Path

from pyxeetb.admin.assets import LOGO_DIR
from pyxeetb.admin.render.commands_page import build_commands_page

_REDIRECT = """<!doctype html>
<meta charset="utf-8">
<title>PyxeeTB commands</title>
<meta http-equiv="refresh" content="0; url=commands/">
<link rel="canonical" href="commands/">
<p><a href="commands/">PyxeeTB commands</a></p>
"""


def build_site(out_dir: Path, prefix: str = "!") -> list[Path]:
    """Writes the site into `out_dir` (created if needed); returns the files written."""
    commands_dir = out_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    logo = LOGO_DIR / "logo.png"
    has_logo = logo.is_file()
    written: list[Path] = []

    page = commands_dir / "index.html"
    # The page is served at <base>/commands/, so the logo one level up is <base>/logo.png.
    page.write_text(
        build_commands_page(prefix, has_logo=has_logo, logo_src="../logo.png", favicon_src="../logo.png"),
        encoding="utf-8",
    )
    written.append(page)
    if has_logo:
        shutil.copyfile(logo, out_dir / "logo.png")
        written.append(out_dir / "logo.png")
    (out_dir / "index.html").write_text(_REDIRECT, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    written += [out_dir / "index.html", out_dir / ".nojekyll"]
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("output", type=Path, help="directory to write the static site into")
    parser.add_argument("--prefix", default="!", help="command prefix shown on the page (default: !)")
    args = parser.parse_args(argv)
    for path in build_site(args.output, args.prefix):
        print(escape(str(path), quote=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
