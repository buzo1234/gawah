from datetime import date

import pytest

from app.contracts import (
    EVENTS, MEMORY_STATE, Audience, CallEnded, CallStarted, Fact, FactKind, FactRecorded, FactSource,
    ItemKey, JudgeSpeak, JudgeSpoke, MemoryQueries, OwedRow, Role, SpeakReason, TermView, TranscriptLine,
    clip_path, empty_checklist, parse_event,
)
from app.store import Store
from fakes.samples import sample_events

PLAN_EVENTS = {
    "deal.requested", "call.opened", "call.started", "call.ended", "transcript.line", "checklist.updated",
    "judge.speak", "judge.spoke", "terms.confirmed", "terms.disputed", "contract.ready",
    "record.received", "record.confirm_requested", "record.confirmed", "reply.timeout",
    "whatsapp.message", "whatsapp.voice_note", "fact.recorded", "fact.conflict", "fact.changed", "agent.note",
}
CREW_EVENTS = {"fact.recorded", "fact.conflict", "fact.changed", "agent.note"}


def test_every_plan_event_has_a_model_and_a_sample():
    assert set(EVENTS) == PLAN_EVENTS
    assert {e.name for e in sample_events()} == PLAN_EVENTS


@pytest.mark.parametrize("event", sample_events(), ids=lambda e: e.name)
def test_event_round_trips_through_json(event):
    parsed = parse_event(event.model_dump_json())
    assert type(parsed) is type(event)
    assert parsed == event
    assert parse_event(event.model_dump(mode="json")) == event


def test_unknown_fields_are_ignored_and_unknown_names_rejected():
    line = sample_events()[2].model_dump(mode="json")
    assert parse_event({**line, "added_later": 1}).text == line["text"]
    with pytest.raises(ValueError):
        parse_event({**line, "name": "no.such.event"})


def test_judge_speak_carries_what_whom_which_item_and_why():
    speak = JudgeSpeak(
        deal_id="d1", instruction="Ask which amount is right.", to=Audience.BOTH,
        reason=SpeakReason.CONFLICTING_FIGURES, item=ItemKey.AMOUNT,
    )
    data = speak.model_dump(mode="json")
    assert (data["to"], data["reason"], data["item"]) == ("both", "conflicting_figures", "amount")
    assert {r.value for r in SpeakReason} == {
        "addressed_directly", "term_unclear", "conflicting_figures", "wrapping_up",
        "ambiguous", "contradicts_record", "change_proposed", "open_terms", "unanswered_question", "read_back",
    }


def test_checklist_has_the_six_items_and_roles_flip():
    assert [i.key.value for i in empty_checklist()] == [
        "work", "amount", "advance", "balance", "dates", "late_or_unfinished",
    ]
    assert Role.HIRER.other is Role.WORKER and Role.WORKER.other is Role.HIRER


def test_events_sent_before_the_crew_fields_still_parse_with_defaults():
    old = {"deal_id": "d1", "ts": "2026-11-21T10:00:00Z", "event_id": "e1"}
    started = parse_event({**old, "name": "call.started", "people": [], "kind": "deal", "room": "r"})
    ended = parse_event({**old, "name": "call.ended", "room": "r"})
    line = parse_event({**old, "name": "transcript.line", "speaker": "hirer", "text": "haan", "start": 1, "end": 2})
    speak = parse_event({**old, "name": "judge.speak", "instruction": "Ask.", "to": "both", "reason": "term_unclear"})
    spoke = parse_event({**old, "name": "judge.spoke", "text": "Haan ji?"})
    assert (type(started), type(ended), type(line)) == (CallStarted, CallEnded, TranscriptLine)
    assert (started.call_no, ended.call_no, line.call_no) == (1, 1, 1)
    assert (speak.fact_ids, speak.question, spoke.clip_fact_id) == ([], None, None)


def test_judge_speak_and_spoke_carry_the_facts_and_the_question():
    speak = JudgeSpeak(
        deal_id="d1", instruction="Answer from the facts.", to=Audience.HIRER, reason=SpeakReason.ADDRESSED_DIRECTLY,
        fact_ids=["f1", "f2"], question="Gawah, advance kitna tay hua tha?",
    )
    spoke = JudgeSpoke(deal_id="d1", text="8,000 tay hua tha. Sunaiye.", speak_id=speak.event_id, clip_fact_id="f1")
    assert parse_event(speak.model_dump_json()) == speak
    assert parse_event(spoke.model_dump_json()).clip_fact_id == "f1"


async def test_the_event_log_keeps_the_crew_events(bus, settings):
    store = Store(settings.database_path)
    await store.open()
    bus.subscribe_all(store.record_event)
    crew = [e for e in sample_events("d-crew") if e.name in CREW_EVENTS]
    assert {e.name for e in crew} == CREW_EVENTS
    for event in crew:
        bus.publish(event)
    await bus.drain()
    await store.close()

    reopened = Store(settings.database_path)
    await reopened.open()
    assert await reopened.events("d-crew") == crew
    [recorded] = await reopened.events("d-crew", "fact.recorded")
    assert isinstance(recorded, FactRecorded) and recorded.fact == crew[0].fact
    await reopened.close()


def test_a_payment_fact_links_to_the_term_it_counts_towards():
    advance = next(e for e in sample_events() if isinstance(e, FactRecorded)).fact
    paid = Fact(
        deal_id="d1", text="The hirer paid 5,000 rupees of the advance.", item=ItemKey.ADVANCE,
        kind=FactKind.PAYMENT, value="5,000 rupees", value_rupees=5000, value_date=date(2026, 11, 23),
        said_by=Role.HIRER, source=FactSource.SCREENSHOT, record_id="r1",
        media_url="https://example.invalid/upi.jpg", counts_towards=advance.id,
    )
    data = paid.model_dump(mode="json")
    assert (data["value_date"], data["counts_towards"]) == ("2026-11-23", advance.id)
    assert Fact.model_validate_json(paid.model_dump_json()) == paid
    assert advance.value_rupees == 8000 and advance.valid_from is not None


class _Memory:
    async def get_term(self, deal_id: str, item: ItemKey) -> TermView:
        return TermView(item=item)

    async def owed(self, deal_id: str) -> list[OwedRow]:
        return [OwedRow(item=ItemKey.ADVANCE, agreed_rupees=8000, paid_rupees=5000, owed_rupees=3000, payment_fact_ids=["f2"])]

    async def search(self, deal_id: str, query: str, k: int = 5) -> list[Fact]:
        return []

    async def clip(self, fact_id: str) -> bytes | None:
        return None


async def test_memory_queries_is_a_protocol_a_stream_can_check():
    memory = _Memory()
    assert isinstance(memory, MemoryQueries) and not isinstance(object(), MemoryQueries)
    assert MEMORY_STATE == "memory" and clip_path("f1") == "/memory/clip/f1"
    [row] = await memory.owed("d1")
    assert OwedRow.model_validate_json(row.model_dump_json()) == row
    view = TermView(item=ItemKey.ADVANCE, current=None, history=[])
    assert TermView.model_validate_json(view.model_dump_json()) == view
