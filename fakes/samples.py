"""One filled-in example of every event, for tests and for building a view of each."""

from app.contracts import (
    Audience, Backing, CallEnded, CallStarted, ChecklistItem, ChecklistUpdated, ContractReady,
    DealRequested, Direction, Event, ItemKey, ItemState, JudgeSpeak, JudgeSpoke, Person, Record,
    RecordConfirmed, RecordConfirmRequested, RecordKind, RecordReceived, ReplyTimeout, Role,
    SpeakReason, TermsConfirmed, TermsDisputed, TranscriptLine, WhatsAppMessage, empty_checklist,
)
from fakes import RAMESH, SUNITA


def sample_events(deal_id: str = "sample") -> list[Event]:
    items = empty_checklist()
    items[1] = ChecklistItem(
        key=ItemKey.AMOUNT, state=ItemState.AGREED, value="24,000 rupees, labour and material",
        confidence=0.93, source_text="24 hazaar final. Labour, material, putty, sab ismein.", line_no=14,
    )
    record = Record(
        sender=Role.HIRER, kind=RecordKind.ADVANCE, backing=Backing.BACKED, text="Advance bhej diya",
        media_url="https://example.invalid/screenshot.jpg", amount=8000, date="23 Nov 2026",
        transaction_id="T2611230001",
    )
    cash = Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, text="2,000 cash diya", amount=2000)
    return [
        DealRequested(
            deal_id=deal_id, requested_by=SUNITA, other=Person(role=Role.WORKER, phone=RAMESH.phone),
            text="Ramesh painter se deal karni hai",
        ),
        CallStarted(deal_id=deal_id, people=[SUNITA, RAMESH], room=f"deal-{deal_id}"),
        TranscriptLine(
            deal_id=deal_id, speaker=Role.WORKER, text="Theek hai ji, 24 hazaar final.",
            start=41.2, end=44.0, line_no=14,
        ),
        ChecklistUpdated(deal_id=deal_id, items=items, changed=[ItemKey.AMOUNT]),
        JudgeSpeak(
            deal_id=deal_id, instruction="Ask when the balance will be paid.", to=Audience.HIRER,
            reason=SpeakReason.TERM_UNCLEAR, item=ItemKey.BALANCE, after_line=19,
        ),
        JudgeSpoke(
            deal_id=deal_id, text="Sunita ji, baaki paise kab denge?", to=Audience.HIRER,
            reason=SpeakReason.TERM_UNCLEAR, item=ItemKey.BALANCE, start=92.0, end=94.5,
        ),
        CallEnded(
            deal_id=deal_id, people=[SUNITA, RAMESH], room=f"deal-{deal_id}", duration=155.4,
            recording_keys={"hirer": f"recordings/{deal_id}/hirer.wav"},
        ),
        TermsConfirmed(deal_id=deal_id, person=Role.WORKER, item=ItemKey.AMOUNT, value="24,000 rupees", said="haan sahi hai"),
        TermsDisputed(deal_id=deal_id, person=Role.WORKER, item=ItemKey.DATES, value="Monday to Friday", said="nahi, Saturday tak bola tha"),
        ContractReady(deal_id=deal_id, pdf_key=f"contracts/{deal_id}.pdf", text="Kaam: 2BHK flat ki painting...", items=items),
        RecordReceived(deal_id=deal_id, record=record),
        RecordConfirmRequested(
            deal_id=deal_id, record_id=cash.id, record=cash, confirm_by=Role.WORKER,
            question="Sunita ji keh rahi hain 2,000 cash diya. Sahi hai?",
        ),
        RecordConfirmed(deal_id=deal_id, record_id=cash.id, confirmed_by=Role.WORKER),
        ReplyTimeout(deal_id=deal_id, person=Role.WORKER, ask="Kya 2,000 cash mila?", record_id=cash.id, waited_seconds=120),
        WhatsAppMessage(
            deal_id=deal_id, direction=Direction.OUT, phone=RAMESH.phone, role=Role.WORKER,
            text="Ramesh ji, yeh aapka contract hai.", media_url="https://example.invalid/contract.pdf",
            media_type="application/pdf", simulated=True,
        ),
    ]
