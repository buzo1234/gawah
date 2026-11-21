"""Shared event and data types. Frozen after the scaffold.

Streams talk to each other only through the events below. Changing this file
needs one named person to approve it on main; everyone else then rebases.
Unknown fields are ignored on parse, so adding an optional field is safe.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter


def new_id() -> str:
    return uuid4().hex[:12]


# ---------- data types ----------


class Role(StrEnum):
    HIRER = "hirer"
    WORKER = "worker"

    @property
    def other(self) -> "Role":
        return Role.WORKER if self is Role.HIRER else Role.HIRER


class Audience(StrEnum):
    HIRER = "hirer"
    WORKER = "worker"
    BOTH = "both"


class Person(BaseModel):
    role: Role
    name: str | None = None
    phone: str | None = None  # with country code, like +9198XXXXXXXX


class DealStatus(StrEnum):
    REQUESTED = "requested"
    IN_CALL = "in_call"
    CALL_ENDED = "call_ended"
    CONTRACT_READY = "contract_ready"


class Deal(BaseModel):
    id: str
    people: list[Person] = []
    status: DealStatus = DealStatus.REQUESTED
    created_at: datetime | None = None

    def person(self, role: Role) -> Person | None:
        return next((p for p in self.people if p.role == role), None)


class ItemKey(StrEnum):
    WORK = "work"  # what exactly is to be done
    AMOUNT = "amount"  # how much, and what it covers
    ADVANCE = "advance"  # how much, and when
    BALANCE = "balance"  # when it is paid, and against what
    DATES = "dates"  # start and finish
    LATE_OR_UNFINISHED = "late_or_unfinished"  # what happens if late or left unfinished


class ItemState(StrEnum):
    PENDING = "pending"
    AGREED = "agreed"


class ChecklistItem(BaseModel):
    key: ItemKey
    state: ItemState = ItemState.PENDING
    value: str | None = None  # the agreed term in plain words, e.g. "24,000 rupees, labour and material"
    confidence: float | None = None  # 0 to 1
    source_text: str | None = None  # the words the value was taken from
    line_no: int | None = None  # the transcript line it was taken from
    note: str | None = None  # e.g. "two figures said: 13,000 and 14,000"


def empty_checklist() -> list[ChecklistItem]:
    return [ChecklistItem(key=key) for key in ItemKey]


class SpeakReason(StrEnum):
    ADDRESSED_DIRECTLY = "addressed_directly"  # someone spoke to Gawah
    TERM_UNCLEAR = "term_unclear"  # they moved on and left a term unclear
    CONFLICTING_FIGURES = "conflicting_figures"  # two different figures for the same term
    WRAPPING_UP = "wrapping_up"  # they are wrapping up (items pending, or the final read-back)


class CallKind(StrEnum):
    DEAL = "deal"  # both people and Gawah
    CALLBACK = "callback"  # one person and Gawah, to confirm terms


class RecordKind(StrEnum):
    ADVANCE = "advance"
    PAYMENT = "payment"
    WORK_DAY = "work_day"
    MILESTONE = "milestone"
    WORK_DONE = "work_done"
    OTHER = "other"


class Backing(StrEnum):
    BACKED = "backed"  # the proof stands on its own; logged directly
    UNBACKED = "unbacked"  # one person's word; the other must confirm


class Record(BaseModel):
    id: str = Field(default_factory=new_id)
    sender: Role
    kind: RecordKind = RecordKind.OTHER
    backing: Backing = Backing.UNBACKED
    text: str | None = None  # the message as sent
    media_url: str | None = None  # the screenshot, if any
    amount: float | None = None  # rupees
    date: str | None = None  # as read from the message or screenshot
    transaction_id: str | None = None
    extra: dict[str, Any] = {}  # any other extracted fields
    confirmed: bool | None = None  # None until the other person answers


# ---------- conventions that are not events ----------
# Links are built from the deal id, so no event is needed to pass them around.
# Prefix them with settings.public_base_url before sending.

WHATSAPP_WEBHOOK_PATH = "/whatsapp/webhook"  # served by whatsapp


def call_path(deal_id: str, role: Role) -> str:
    """The deal call page for one person. Served by bridge (app/call)."""
    return f"/call/{deal_id}/{role.value}"


def callback_path(deal_id: str, role: Role) -> str:
    """The one-to-one call-back page for one person. Served by mouth."""
    return f"/callback/{deal_id}/{role.value}"


# ---------- events ----------


class Event(BaseModel):
    name: str
    deal_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_id: str = Field(default_factory=new_id)


class DealRequested(Event):
    """Sent by whatsapp when someone asks Gawah to witness a deal. It makes the deal id.
    Listened to by bridge (prepare the room) and dashboard."""

    name: Literal["deal.requested"] = "deal.requested"
    requested_by: Person
    other: Person  # usually only the phone is known
    text: str | None = None  # the message that asked


class CallStarted(Event):
    """Sent by bridge when a deal call starts, and by mouth for a call-back (kind=callback).
    Listened to by brain, mouth, whatsapp, dashboard."""

    name: Literal["call.started"] = "call.started"
    people: list[Person] = []  # the people in the room
    kind: CallKind = CallKind.DEAL
    room: str | None = None


class CallEnded(Event):
    """Sent by whoever sent call.started for this call.
    Listened to by brain, mouth, contract, whatsapp, dashboard."""

    name: Literal["call.ended"] = "call.ended"
    people: list[Person] = []
    kind: CallKind = CallKind.DEAL
    room: str | None = None
    duration: float | None = None  # seconds
    recording_keys: dict[str, str] = {}  # role -> S3 key of that person's audio
    reason: str | None = None


class TranscriptLine(Event):
    """Sent by bridge (ears) for each finished line of speech. Also sent by the replayer.
    Listened to by brain, mouth (to know when someone is talking), dashboard."""

    name: Literal["transcript.line"] = "transcript.line"
    speaker: Role
    text: str
    start: float  # seconds from the start of the call
    end: float
    line_no: int | None = None  # 1-based position in the call; set it if you can


class ChecklistUpdated(Event):
    """Sent by brain whenever an item changes. Always carries all six items.
    Listened to by mouth (read-back, call-back), contract, dashboard."""

    name: Literal["checklist.updated"] = "checklist.updated"
    items: list[ChecklistItem]
    changed: list[ItemKey] = []


class JudgeSpeak(Event):
    """Sent by brain when the Judge should speak. Listened to by mouth and dashboard.
    The instruction is plain text for the voice model to phrase in Hindi. It only ever
    asks a question or reads terms back; it never suggests a term or judges one."""

    name: Literal["judge.speak"] = "judge.speak"
    instruction: str  # what to ask, e.g. "Ask when the balance will be paid."
    to: Audience
    reason: SpeakReason
    item: ItemKey | None = None  # None when it is not about one item
    after_line: int | None = None  # the transcript line that triggered it


class JudgeSpoke(Event):
    """Sent by mouth after the Judge has spoken. Listened to by brain (to keep the gap
    between interruptions) and dashboard."""

    name: Literal["judge.spoke"] = "judge.spoke"
    text: str  # what was actually said
    speak_id: str | None = None  # event_id of the judge.speak it answers
    to: Audience | None = None
    reason: SpeakReason | None = None
    item: ItemKey | None = None
    start: float | None = None  # seconds from the start of the call
    end: float | None = None
    interrupted: bool = False  # cut off because someone talked over it


class TermsConfirmed(Event):
    """Sent by mouth when a person confirms a term on the call-back.
    Listened to by contract, whatsapp, dashboard."""

    name: Literal["terms.confirmed"] = "terms.confirmed"
    person: Role
    item: ItemKey | None = None  # None means all terms
    value: str | None = None  # the term as read to them
    said: str | None = None  # what the person said


class TermsDisputed(Event):
    """Sent by mouth when a person disputes a term on the call-back.
    Listened to by contract, whatsapp, dashboard."""

    name: Literal["terms.disputed"] = "terms.disputed"
    person: Role
    item: ItemKey | None = None
    value: str | None = None
    said: str | None = None
    clip_url: str | None = None  # the clip played back to them, if any


class ContractReady(Event):
    """Sent by contract when the contract is written. Listened to by whatsapp (send it
    to both) and dashboard."""

    name: Literal["contract.ready"] = "contract.ready"
    pdf_url: str | None = None  # short-lived signed link
    pdf_key: str | None = None  # S3 key, to sign a fresh link later
    voice_summary_url: str | None = None
    voice_summary_key: str | None = None
    text: str | None = None  # the contract text
    items: list[ChecklistItem] = []


class RecordReceived(Event):
    """Sent by whatsapp when a record comes in (and by the dashboard's second-phone panel).
    Listened to by dashboard."""

    name: Literal["record.received"] = "record.received"
    record: Record


class RecordConfirmRequested(Event):
    """Sent by whatsapp when it asks the other person about an unbacked record.
    Listened to by dashboard."""

    name: Literal["record.confirm_requested"] = "record.confirm_requested"
    record_id: str
    confirm_by: Role
    record: Record | None = None
    question: str | None = None  # what was asked


class RecordConfirmed(Event):
    """Sent by whatsapp when the other person answers. confirmed=False means they said no.
    Listened to by dashboard."""

    name: Literal["record.confirmed"] = "record.confirmed"
    record_id: str
    confirmed_by: Role
    confirmed: bool = True
    record: Record | None = None


class ReplyTimeout(Event):
    """Sent by whatsapp when a person has not replied in time.
    Listened to by whatsapp (send the follow-up link), mouth (stretch: ring them), dashboard."""

    name: Literal["reply.timeout"] = "reply.timeout"
    person: Role  # who to follow up with
    ask: str  # what to ask them
    record_id: str | None = None
    waited_seconds: float | None = None


AnyEvent = Annotated[
    DealRequested
    | CallStarted
    | CallEnded
    | TranscriptLine
    | ChecklistUpdated
    | JudgeSpeak
    | JudgeSpoke
    | TermsConfirmed
    | TermsDisputed
    | ContractReady
    | RecordReceived
    | RecordConfirmRequested
    | RecordConfirmed
    | ReplyTimeout,
    Field(discriminator="name"),
]

_adapter: TypeAdapter[AnyEvent] = TypeAdapter(AnyEvent)

EVENTS: dict[str, type[Event]] = {
    cls.model_fields["name"].default: cls for cls in Event.__subclasses__()
}


def parse_event(data: str | bytes | dict[str, Any]) -> AnyEvent:
    """Turn JSON (or a dict) back into the right event, picked by its name."""
    if isinstance(data, (str, bytes)):
        return _adapter.validate_json(data)
    return _adapter.validate_python(data)
