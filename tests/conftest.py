import pytest

from app.bus import Bus
from app.config import Settings


@pytest.fixture
async def bus():
    """A started bus. Call `await bus.drain()` before asserting on what handlers saw."""
    bus = Bus()
    bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings that read no .env and keep the database in a temp folder."""
    return Settings(_env_file=None, database_path=str(tmp_path / "test.db"))
