import pytest

from app.bus import Bus
from app.config import Settings


@pytest.fixture(autouse=True)
def _twilio_unless_a_test_says_meta(monkeypatch):
    """The whatsapp stream reads WHATSAPP_PROVIDER and META_APP_SECRET from the shell or
    .env even when a test's settings read no .env. Pin them, so the .env never decides."""
    monkeypatch.setenv("WHATSAPP_PROVIDER", "twilio")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("CALLBACKS_ENABLED", "true")  # app/records/no_callbacks.py: a test that wants them off says so
    # The server's settings: no shell decides whether a test runs as a public server.
    monkeypatch.delenv("ACCESS_KEY", raising=False)
    monkeypatch.delenv("GAWAH_SECRET_ID", raising=False)


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
