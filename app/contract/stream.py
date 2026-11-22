"""Watches each deal's confirmations and, once both people have confirmed, writes the
contract, the PDF and the spoken summary, uploads them, and publishes contract.ready.
When a change both confirmed reaches memory, it writes the next version. On start it
writes whatever the event log says is due and was never written (a restart mid-write)."""

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.bus import Bus
from app.contract import chain, document, page
from app.contract.pdf import page_count
from app.contract.terms import also_agreed, change_list, resolve
from app.contract.trigger import WATCHED, Call, DealState
from app.contract.writer import Writer, write_draft
from app.contracts import (
    AgentNote, CallKind, ChecklistItem, ContractReady, CrewAgent, Event, Fact, ItemKey, MemoryQueries, Role,
    TermsConfirmed,
)
from app.log import deal_log, mask_phone
from app.store import Store

LOG = "gawah.contract"
RETRY_SECONDS = 10.0  # a failed write (Chrome, S3, OpenAI) is tried once more after this


class Speaker(Protocol):
    async def speak(self, text: str) -> bytes: ...


class Files(Protocol):
    async def upload(self, path: str, key: str, content_type: str | None = None) -> str: ...
    async def signed_url(self, key: str, expires_seconds: int = 900) -> str: ...


RenderPdf = Callable[[str, Path], Awaitable[None]]
Fingerprint = Callable[[str], Awaitable[str]]  # a signed link in, the file's SHA-256 out
Memory = Callable[[], MemoryQueries | None]  # the running memory, looked up when a contract is written


class ContractStream:
    def __init__(
        self, bus: Bus, store: Store, writer: Writer, speaker: Speaker, files: Files,
        render_pdf: RenderPdf, fingerprint: Fingerprint, memory: Memory = lambda: None,
        retry_after: float = RETRY_SECONDS,
    ) -> None:
        self._bus, self._store = bus, store
        self._writer, self._speaker, self._files, self._render_pdf = writer, speaker, files, render_pdf
        self._fingerprint, self._memory, self._retry_after = fingerprint, memory, retry_after
        self._states: dict[str, DealState] = {}
        self._loading = asyncio.Lock()  # one DealState per deal, however many ask for it at once
        self._seen: set[str] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._resuming: asyncio.Task[None] | None = None

    async def on_event(self, event: Event) -> None:
        if not isinstance(event, WATCHED):
            return
        state = await self._state(event.deal_id)
        if event.event_id not in self._seen:  # the store may already have had this one
            state.apply(event)
        self._start(event.deal_id, state)

    async def start(self) -> None:
        """On startup, in the background so startup does not wait for it."""
        self._resuming = asyncio.create_task(self._resume())

    async def idle(self) -> None:
        """Wait for the startup catch-up and any contract being written. For tests and shutdown."""
        if self._resuming:
            await asyncio.gather(self._resuming, return_exceptions=True)
        while self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            await asyncio.sleep(0)  # let the finished tasks remove themselves

    async def close(self) -> None:
        for task in [self._resuming, *self._tasks.values()]:
            if task:
                task.cancel()
        await self.idle()

    async def _resume(self) -> None:
        """Write each agreement the event log says is due and never got written: the server
        stopped while it was being written. A deal nobody confirmed can never be due."""
        try:
            confirmed = await self._store.events(name=TermsConfirmed.model_fields["name"].default)
            for deal_id in dict.fromkeys(e.deal_id for e in confirmed):
                state = await self._state(deal_id)
                if self._start(deal_id, state):
                    deal_log(LOG, deal_id).warning(
                        "version %d was due and never written (a restart mid-write?); writing it now", state.versions + 1
                    )
        except Exception:
            logging.getLogger(LOG).exception("CONTRACT CATCH-UP FAILED: agreements due before the restart were not checked")

    async def _state(self, deal_id: str) -> DealState:
        async with self._loading:
            if deal_id not in self._states:
                self._states[deal_id] = await self._from_store(deal_id)
            return self._states[deal_id]

    def _start(self, deal_id: str, state: DealState) -> bool:
        """Start writing if a version is due. At most one write per deal: the one running
        writes every version that falls due while it runs."""
        if deal_id in self._tasks or not state.should_write():
            return False
        task = self._tasks[deal_id] = asyncio.create_task(self._write(deal_id, state))
        task.add_done_callback(lambda _: self._tasks.pop(deal_id, None))
        return True

    async def _from_store(self, deal_id: str) -> DealState:
        """After a restart, catch up on what the deal's earlier events said."""
        state = DealState()
        for event in await self._store.events(deal_id):
            state.apply(event)
            self._seen.add(event.event_id)
        return state

    async def _write(self, deal_id: str, state: DealState) -> None:
        log = deal_log(LOG, deal_id)
        failed = False
        while state.should_write():
            disputes, changes = state.disputes, set(state.landed)
            try:
                ready, note = await self._make(deal_id, state)
            except Exception:
                if failed:
                    log.exception("CONTRACT NOT WRITTEN after one retry, contract.ready not published")
                    return
                failed = True
                log.exception("contract write failed; trying once more in %.0f seconds", self._retry_after)
                await asyncio.sleep(self._retry_after)
                continue
            failed = False
            if state.disputes != disputes:
                log.warning("a term was disputed while the contract was being written; it was thrown away")
                continue
            state.wrote(changes)
            self._bus.publish(ready)
            self._bus.publish(note)
            log.info("contract.ready published: %s and %s", ready.pdf_key, ready.voice_summary_key)

    async def _make(self, deal_id: str, state: DealState) -> tuple[ContractReady, AgentNote]:
        log = deal_log(LOG, deal_id)
        version = state.versions + 1
        checklist, confirmed_at, confirmed_said = state.checklist(), dict(state.confirmed_at), dict(state.confirmed_said)
        said_yes = state.both_said_yes()
        calls = {n: Call(c.started, c.ended) for n, c in state.calls.items()}
        facts, latest, landed, proposed = list(state.facts), state.latest(), list(state.landed.values()), dict(state.proposed)
        new_changes = [new for change_id, (_, new) in state.landed.items() if change_id not in state.written_changes]
        deal = await self._store.deal(deal_id)
        people = {p.role: p for p in deal.people} if deal else {}
        transcript = [line for line in await self._store.transcript(deal_id) if line.kind is CallKind.DEAL]
        log.info(
            "both confirmed, writing version %d of the contract for %s and %s", version,
            *(mask_phone(people[r].phone if r in people else None) for r in Role),
        )
        memory = self._memory()
        current = {key: (await memory.get_term(deal_id, key)).current if memory else None for key in ItemKey}
        starts = {n: c.started for n, c in calls.items() if c.started}
        changes, changed_facts = change_list(landed, proposed, latest, starts)
        lines = {(line.call_no, line.line_no): line for line in transcript if line.line_no is not None}
        terms = resolve(checklist, current, changes, changed_facts, lines, starts, said_yes)
        also = also_agreed(latest, starts)
        items = [t.item for t in terms]
        draft, fingerprints = await asyncio.gather(
            write_draft(self._writer, deal_id, items, transcript, changes, also), self._fingerprints(deal_id, calls)
        )
        head = chain.head(facts)
        if facts and head is None:
            log.warning("the witness chain over %d fact versions does not hold; it is left off the contract", len(facts))
        doc = document.build(
            deal_id=deal_id, people=people, names=draft.names, place=draft.place, terms=terms, bodies=draft.terms,
            confirmed_at=confirmed_at, confirmed_said=confirmed_said, calls=calls, fingerprints=fingerprints,
            now=datetime.now(UTC), version=version, changes=changes, change_texts=draft.changes, also=also,
            also_texts=draft.also, chain=head, facts=latest,
        )
        pdf_key, voice_key = f"contracts/{deal_id}-v{version}.pdf", f"contracts/{deal_id}-v{version}.ogg"
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path, voice_path = Path(tmp) / "contract.pdf", Path(tmp) / "summary.ogg"
            _, voice = await asyncio.gather(self._render_pdf(page.html(doc), pdf_path), self._speaker.speak(draft.summary))
            voice_path.write_bytes(voice)
            log.info("pdf has %d page(s), voice summary is %.1f seconds", page_count(pdf_path.read_bytes()), ogg_seconds(voice))
            # Nothing is published unless every upload and every link worked.
            await self._files.upload(str(pdf_path), pdf_key, "application/pdf")
            await self._files.upload(str(voice_path), voice_key, "audio/ogg")
        written = {i.key: i for i in items}
        ready = ContractReady(
            deal_id=deal_id,
            pdf_key=pdf_key, pdf_url=await self._files.signed_url(pdf_key),
            voice_summary_key=voice_key, voice_summary_url=await self._files.signed_url(voice_key),
            text=doc.text(), items=[written.get(key) or ChecklistItem(key=key) for key in ItemKey],
        )
        return ready, _note(deal_id, version, len(terms), changes, new_changes, head)

    async def _fingerprints(self, deal_id: str, calls: dict[int, Call]) -> dict[tuple[int, Role], str]:
        """The SHA-256 of each person's recording of each call. One that cannot be read is left out."""
        found = {}
        for n, call in sorted(calls.items()):
            for role in Role:
                key = call.ended.recording_keys.get(role.value) if call.ended else None
                if not key:
                    continue
                try:
                    found[(n, role)] = await self._fingerprint(await self._files.signed_url(key))
                except Exception as e:
                    # Only the kind of error: its message can hold the signed link.
                    deal_log(LOG, deal_id).warning(
                        "could not read the %s recording of call %d (%s); its fingerprint is left out",
                        role.value, n, type(e).__name__,
                    )
        return found


def _note(deal_id: str, version: int, terms: int, changes: list, new: list[Fact], head) -> AgentNote:
    text = f"contract v{version} written: {terms} terms"
    if new:
        text += ", " + "; ".join(f"{f.item.value if f.item else 'term'} now {f.value}" for f in new)
    elif changes:
        text += f", {len(changes)} change(s) listed"
    if head:
        text += f", chain {head[1]} links"
    return AgentNote(deal_id=deal_id, agent=CrewAgent.CLERK, text=text[:160], fact_ids=[f.id for f in new])


def ogg_seconds(data: bytes) -> float:
    """Length of an Ogg Opus file: the last page's sample position, at Opus's fixed 48 kHz."""
    last = data.rfind(b"OggS")
    return int.from_bytes(data[last + 6 : last + 14], "little") / 48000 if last >= 0 else 0.0
