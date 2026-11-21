"""Webhook payloads in Meta's shape, and a World with the bot on Meta (against the fake
Graph API in meta_fakes.py), where Sunita and Ramesh are real (verified) phones and Geeta
is a simulated one."""

import pytest
from meta_fakes import API, LOOKASIDE, PHONE_ID, SECRET, TOKEN, VERIFY, FakeGraph
from whatsapp_world import BASE, GEETA, RAMESH, SUNITA, World

from app.store import Store
from app.whatsapp.meta import Meta
from app.whatsapp.meta_inbound import parse_meta
from app.whatsapp.settings import WhatsAppSettings


def meta_settings(tmp_path, **more) -> WhatsAppSettings:
    return WhatsAppSettings(
        _env_file=None, database_path=str(tmp_path / "test.db"), public_base_url=BASE, reply_timeout_seconds=120,
        whatsapp_provider="meta", verified_numbers=f"{SUNITA},{RAMESH}", meta_whatsapp_token=TOKEN,
        meta_phone_number_id=PHONE_ID, meta_verify_token=VERIFY, meta_app_secret=SECRET, **more,
    )


# ---------- webhook payloads, as Meta posts them ----------

def webhook(*messages: dict, names: dict[str, str] | None = None, statuses: list[dict] | None = None) -> dict:
    contacts = [{"profile": {"name": name}, "wa_id": phone.lstrip("+")} for phone, name in (names or {}).items()]
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550000000", "phone_number_id": PHONE_ID}}
    if messages:
        value |= {"contacts": contacts, "messages": list(messages)}
    if statuses:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{"value": value, "field": "messages"}]}]}


_count = iter(range(1, 10_000))


def message(phone: str, kind: str, body: dict | None = None, **more) -> dict:
    raw = {"from": phone.lstrip("+"), "id": f"wamid.IN{next(_count)}", "timestamp": "1795000000", "type": kind}
    if body is not None:
        raw[kind] = body
    return raw | more


def text(phone: str, words: str) -> dict:
    return message(phone, "text", {"body": words})


def tap(phone: str, button_id: str, title: str, on: str = "wamid.OUT1") -> dict:
    return message(phone, "interactive", {"type": "button_reply", "button_reply": {"id": button_id, "title": title}},
                   context={"from": "15550000000", "id": on})


class MetaWorld(World):
    def __init__(self, bus, store, settings, memory=None) -> None:
        self.graph = FakeGraph()
        self._settings_for_meta = settings
        super().__init__(bus, store, settings, memory)

    def wire(self):
        self.provider = self.meta = Meta(self._settings_for_meta, transport=self.graph.transport())
        self.meta.spacing_seconds = 0.0  # the pacing test puts it back
        return super().wire()

    async def post(self, payload: dict) -> list[str]:
        """A webhook from Meta, every message in it handled to the end. Returns their wamids."""
        messages, _, _ = parse_meta(payload, self.meta.media_url)
        for inbound in messages:
            await self.bot.on_message(inbound)
        await self.flush()
        return [m.sid for m in messages]

    async def flush(self) -> None:
        await self.settle()
        await self.bot.outbox.drain()
        await self.settle()


@pytest.fixture
async def meta_world(bus, tmp_path):
    settings = meta_settings(tmp_path)
    store = Store(settings.database_path)
    await store.open()
    world = MetaWorld(bus, store, settings)
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


__all__ = ["API", "GEETA", "LOOKASIDE", "PHONE_ID", "RAMESH", "SUNITA", "MetaWorld", "meta_world"]
