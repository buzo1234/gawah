import pytest

from app.contracts import EVENTS, Audience, ItemKey, JudgeSpeak, Role, SpeakReason, empty_checklist, parse_event
from fakes.samples import sample_events

PLAN_EVENTS = {
    "deal.requested", "call.started", "call.ended", "transcript.line", "checklist.updated",
    "judge.speak", "judge.spoke", "terms.confirmed", "terms.disputed", "contract.ready",
    "record.received", "record.confirm_requested", "record.confirmed", "reply.timeout",
}


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
    }


def test_checklist_has_the_six_items_and_roles_flip():
    assert [i.key.value for i in empty_checklist()] == [
        "work", "amount", "advance", "balance", "dates", "late_or_unfinished",
    ]
    assert Role.HIRER.other is Role.WORKER and Role.WORKER.other is Role.HIRER
