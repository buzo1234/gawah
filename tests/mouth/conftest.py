import pytest

from app.mouth import tuning
from tests.mouth.world import World


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """The real waits, shortened so a test takes a fraction of a second."""
    monkeypatch.setattr(tuning, "OPENING_WAIT_S", 0.3)
    monkeypatch.setattr(tuning, "PAUSE_WAIT_S", 0.3)
    monkeypatch.setattr(tuning, "PREBUFFER_HOLD_MS", 40)
    monkeypatch.setattr(tuning, "BARGE_HOLDOFF_MS", 100)
    monkeypatch.setattr(tuning, "VOICE_TIMEOUT_S", 0.5)


@pytest.fixture
async def world(bus) -> World:
    return World(bus)
