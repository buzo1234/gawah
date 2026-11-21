"""Watches each deal's confirmations and, once both people have confirmed, writes the
contract, the PDF and the spoken summary, uploads them, and publishes contract.ready."""

import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.bus import Bus
from app.contract import document
from app.contract.pdf import page_count
from app.contract.trigger import WATCHED, DealState
from app.contract.writer import Writer, write_draft
from app.contracts import CallKind, ContractReady, Event, Role
from app.log import deal_log, mask_phone
from app.store import Store

LOG = "gawah.contract"


class Speaker(Protocol):
    async def speak(self, text: str) -> bytes: ...


class Files(Protocol):
    async def upload(self, path: str, key: str, content_type: str | None = None) -> str: ...
    async def signed_url(self, key: str, expires_seconds: int = 900) -> str: ...


RenderPdf = Callable[[str, Path], Awaitable[None]]


class ContractStream:
    def __init__(self, bus: Bus, store: Store, writer: Writer, speaker: Speaker, files: Files, render_pdf: RenderPdf) -> None:
        self._bus, self._store = bus, store
        self._writer, self._speaker, self._files, self._render_pdf = writer, speaker, files, render_pdf
        self._states: dict[str, DealState] = {}
        self._seen: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def on_event(self, event: Event) -> None:
        if not isinstance(event, WATCHED):
            return
        state = self._states.get(event.deal_id)
        if state is None:
            state = self._states[event.deal_id] = await self._from_store(event.deal_id)
        if event.event_id not in self._seen:  # the store may already have had this one
            state.apply(event)
        if state.should_write() and event.deal_id not in self._tasks:
            task = self._tasks[event.deal_id] = asyncio.create_task(self._write(event.deal_id, state))
            task.add_done_callback(lambda _: self._tasks.pop(event.deal_id, None))

    async def idle(self) -> None:
        """Wait for any contract being written. For tests and shutdown."""
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            await asyncio.sleep(0)  # let the finished tasks remove themselves

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await self.idle()

    async def _from_store(self, deal_id: str) -> DealState:
        """After a restart, catch up on what the deal's earlier events said."""
        state = DealState()
        for event in await self._store.events(deal_id):
            state.apply(event)
            self._seen.add(event.event_id)
        return state

    async def _write(self, deal_id: str, state: DealState) -> None:
        log = deal_log(LOG, deal_id)
        try:
            while state.should_write():
                version = state.version
                ready = await self._make(deal_id, state)
                if state.version != version:
                    log.warning("a term was disputed while the contract was being written; it was thrown away")
                    continue
                state.written = True
                self._bus.publish(ready)
                log.info("contract.ready published: %s and %s", ready.pdf_key, ready.voice_summary_key)
        except Exception:
            log.exception("CONTRACT NOT WRITTEN, contract.ready not published")

    async def _make(self, deal_id: str, state: DealState) -> ContractReady:
        log = deal_log(LOG, deal_id)
        items, confirmed_at, call_ended_at = list(state.items), dict(state.confirmed_at), state.call_ended_at
        deal = await self._store.deal(deal_id)
        people = {p.role: p for p in deal.people} if deal else {}
        transcript = [line for line in await self._store.transcript(deal_id) if line.kind is CallKind.DEAL]
        log.info(
            "both confirmed, writing the contract for %s and %s",
            *(mask_phone(people[r].phone if r in people else None) for r in Role),
        )
        draft = await write_draft(self._writer, items, transcript)
        doc = document.build(
            deal_id, people, draft.names, items, draft.terms, transcript, confirmed_at, call_ended_at, datetime.now(UTC)
        )
        pdf_key, voice_key = f"contracts/{deal_id}.pdf", f"contracts/{deal_id}.ogg"
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path, voice_path = Path(tmp) / "contract.pdf", Path(tmp) / "summary.ogg"
            _, voice = await asyncio.gather(self._render_pdf(doc.html(), pdf_path), self._speaker.speak(draft.summary))
            voice_path.write_bytes(voice)
            log.info("pdf has %d page(s), voice summary is %.1f seconds", page_count(pdf_path.read_bytes()), ogg_seconds(voice))
            # Nothing is published unless every upload and every link worked.
            await self._files.upload(str(pdf_path), pdf_key, "application/pdf")
            await self._files.upload(str(voice_path), voice_key, "audio/ogg")
        return ContractReady(
            deal_id=deal_id,
            pdf_key=pdf_key, pdf_url=await self._files.signed_url(pdf_key),
            voice_summary_key=voice_key, voice_summary_url=await self._files.signed_url(voice_key),
            text=doc.text(), items=items,
        )


def ogg_seconds(data: bytes) -> float:
    """Length of an Ogg Opus file: the last page's sample position, at Opus's fixed 48 kHz."""
    last = data.rfind(b"OggS")
    return int.from_bytes(data[last + 6 : last + 14], "little") / 48000 if last >= 0 else 0.0
