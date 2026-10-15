import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyxeetb.db import Database  # noqa: E402
from pyxeetb.settings import LiveSettings  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def make_db(tmp_path):
    """Factory returning a connected Database; closed automatically."""
    opened = []

    async def _make(name="test.db"):
        db = Database(tmp_path / name)
        await db.connect()
        opened.append(db)
        return db

    yield _make
    for db in opened:
        run(db.close())


async def make_settings(db):
    """A LiveSettings backed by `db`, loaded (all defaults)."""
    settings = LiveSettings(db)
    await settings.load()
    return settings
