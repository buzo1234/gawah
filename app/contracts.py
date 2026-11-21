"""Shared event and data types. Frozen after the scaffold.

Streams talk to each other only through the events below. Changing this file
needs one named person to approve it on main; everyone else then rebases.
Unknown fields are ignored on parse, so adding an optional field is safe.
"""

from datetime import UTC, datetime
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal
from typing import Protocol, runtime_checkable
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
    AMBIGUOUS = "ambiguous"  # an agreement that can mean two things, e.g. "Monday tak"
    CONTRADICTS_RECORD = "contradicts_record"  # contradicts a fact already agreed or confirmed
    CHANGE_PROPOSED = "change_proposed"  # a change to an agreed term, no longer bargained: both should agree to it


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


class Direction(StrEnum):
    IN = "in"  # from a person to Gawah
    OUT = "out"  # from Gawah to a person


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


class FactKind(StrEnum):
    TERM = "term"
    PAYMENT = "payment"
    WORK = "work"
    CHANGE = "change"
    OTHER = "other"


class FactStatus(StrEnum):
    SAID = "said"  # one person said it
    AGREED = "agreed"  # the other person accepted it
    CONFIRMED = "confirmed"  # confirmed on a call-back, by voice, or on WhatsApp
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"  # a later fact replaces it


class FactSource(StrEnum):
    CALL = "call"
    CALLBACK = "callback"
    VOICE_NOTE = "voice_note"
    TEXT = "text"
    SCREENSHOT = "screenshot"
    RECORD = "record"


class Fact(BaseModel):
    """One thing the deal rests on, kept by memory. The event log stays the source of
    truth: memory's fact store is built from fact.recorded events and can be rebuilt from
    them. A fact is never edited in place: a new status is a new version with the same id,
    and a new value is a new fact whose `replaces` names the old one (which is sent again
    as superseded, with superseded_at set). Every version is one link in the witness chain."""

    id: str = Field(default_factory=new_id)
    deal_id: str
    text: str  # the fact in one plain English sentence, e.g. "The advance is 8,000 rupees."
    item: ItemKey | None = None  # the contract item it belongs to, if any
    kind: FactKind = FactKind.OTHER
    value: str | None = None  # in plain words, e.g. "8,000 rupees, paid on Monday"
    value_rupees: int | None = None  # the value as whole rupees, when it is an amount
    value_date: date | None = None  # the value as a date, when it can be pinned down
    said_by: Role | None = None
    agreed_by: list[Role] = []
    confirmed_by: list[Role] = []
    status: FactStatus = FactStatus.SAID
    source: FactSource = FactSource.CALL
    quote: str | None = None  # the words it was taken from; a fact with no source is dropped
    call_no: int | None = None  # for a call or call-back: the deal call, as in call.started
    line_no: int | None = None  # the transcript line, as in transcript.line
    start: float | None = None  # seconds from that call's start, to cut the audio clip
    end: float | None = None
    record_id: str | None = None  # for a record or WhatsApp message: the Record it came from
    media_url: str | None = None  # the screenshot, voice note, or message it came from
    valid_from: datetime | None = None  # when it became true
    superseded_at: datetime | None = None  # when a later fact replaced it
    replaces: str | None = None  # the id of the fact this one replaces
    counts_towards: str | None = None  # for a payment or work: the id of the term fact it settles
    hash: str | None = None  # sha256 hex of this version and the previous link's hash


# ---------- conventions that are not events ----------
# Links are built from the deal id, so no event is needed to pass them around.
# Prefix them with settings.public_base_url before sending.

# Served by whatsapp. The dashboard's second-phone panel posts here too, in the shape
# the real provider sends, instead of publishing record events itself.
WHATSAPP_WEBHOOK_PATH = "/whatsapp/webhook"

# The deal_id of an event that belongs to no deal yet: a person's first WhatsApp messages
# arrive before deal.requested makes the deal id. The store keeps no deal under this id.
NO_DEAL = "no-deal"


def call_path(deal_id: str, role: Role) -> str:
    """The deal call page for one person. Served by bridge (app/call)."""
    return f"/call/{deal_id}/{role.value}"


def callback_path(deal_id: str, role: Role) -> str:
    """The one-to-one call-back page for one person. Served by mouth."""
    return f"/callback/{deal_id}/{role.value}"


def clip_path(fact_id: str) -> str:
    """The audio clip of a fact, as served by memory: what MemoryQueries.clip returns."""
    return f"/memory/clip/{fact_id}"


# ---------- memory queries ----------
# Facts are a small versioned graph (replaces, counts_towards) with vector search beside it.


class TermView(BaseModel):
    item: ItemKey
    current: Fact | None = None  # the confirmed fact if any, else the agreed one, else None
    history: list[Fact] = []  # every version and offer for this item, oldest first


class OwedRow(BaseModel):
    """One money term (amount, advance, or balance), in whole rupees."""

    item: ItemKey
    agreed_rupees: int | None = None  # None while no figure is agreed
    paid_rupees: int = 0
    owed_rupees: int | None = None  # agreed less paid; None while no figure is agreed
    payment_fact_ids: list[str] = []  # the payment facts counted in paid_rupees


# The name memory sets on app.state: other streams reach it as app.state.memory.
MEMORY_STATE = "memory"


@runtime_checkable
class MemoryQueries(Protocol):
    """What memory answers. The running implementation is app.state.memory (MEMORY_STATE),
    set by memory's register(); other streams type it as MemoryQueries and never import
    app.memory. Answers come from the fact store, which is built from the event log."""

    async def get_term(self, deal_id: str, item: ItemKey) -> TermView: ...

    async def owed(self, deal_id: str) -> list[OwedRow]:
        """One row per money term: amount, advance, balance."""
        ...

    async def search(self, deal_id: str, query: str, k: int = 5) -> list[Fact]:
        """Semantic search over the deal's facts and transcript lines, best first; confirmed
        ranks above agreed above said. A line no fact covers comes back as a said fact
        built from that line (its quote, call_no, line_no, start, end)."""
        ...

    async def clip(self, fact_id: str) -> bytes | None:
        """The audio where the fact was said: a WAV file, 24 kHz mono, with a little padding.
        None if there is no recording."""
        ...


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
    call_no: int = 1  # the deal call within the deal: 1 for the first, 2 for a follow-up


class CallOpened(Event):
    """Sent by bridge when a person opens a deal call room and the other person is not there
    yet, for call 2 and later only (the first call's links go out with deal.requested).
    Listened to by whatsapp (tell the other person, with their call link) and dashboard."""

    name: Literal["call.opened"] = "call.opened"
    call_no: int  # as in call.started
    opened_by: Role  # the person who opened the room
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
    call_no: int = 1  # as in call.started


class TranscriptLine(Event):
    """Sent by bridge (ears) for each finished line of speech. Also sent by the replayer.
    Listened to by brain, mouth (to know when someone is talking), dashboard."""

    name: Literal["transcript.line"] = "transcript.line"
    speaker: Role
    text: str
    start: float  # seconds from the start of the call
    end: float
    line_no: int | None = None  # 1-based position in the call; set it if you can
    kind: CallKind = CallKind.DEAL  # callback lines are not part of the deal call
    call_no: int = 1  # as in call.started; line_no counts from 1 again in each call


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
    fact_ids: list[str] = []  # the facts it is about
    question: str | None = None  # what someone asked Gawah, when it is answering them


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
    clip_fact_id: str | None = None  # the fact whose audio clip was played, if any


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
    """Sent by whatsapp when a record comes in. Listened to by dashboard."""

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


class WhatsAppMessage(Event):
    """Sent by whatsapp for every WhatsApp message in or out, so the conversation is in the
    event log. deal_id is NO_DEAL until the deal exists. Listened to by dashboard (the
    second-phone panel shows what Gawah sent to a simulated number)."""

    name: Literal["whatsapp.message"] = "whatsapp.message"
    direction: Direction
    phone: str  # the person's number, with country code
    role: Role | None = None  # None before a deal exists
    text: str | None = None
    media_url: str | None = None  # a screenshot, a document, or a voice note
    media_type: str | None = None  # its content type, e.g. image/jpeg
    simulated: bool = False  # True: a simulated second phone, so nothing went through the provider
    provider_id: str | None = None  # the provider's message id


class FactRecorded(Event):
    """Sent by memory for a new fact, or a new version of one. The latest version of each
    id is the fact as it stands. Listened to by brain, mouth, contract, dashboard."""

    name: Literal["fact.recorded"] = "fact.recorded"
    fact: Fact


class FactConflict(Event):
    """Sent by memory when something just said contradicts a fact already agreed or
    confirmed. Listened to by brain (a moment to speak) and dashboard."""

    name: Literal["fact.conflict"] = "fact.conflict"
    fact_ids: list[str]  # the facts it contradicts
    explanation: str  # one sentence, e.g. "Says 25,000; the advance was agreed at 22,000."
    said: str | None = None  # the words that triggered it
    speaker: Role | None = None
    call_no: int | None = None  # None when it came from WhatsApp
    line_no: int | None = None
    confidence: float | None = None  # 0 to 1


class ChangeStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED_ONE = "confirmed_one"  # one person has said yes
    CONFIRMED_BOTH = "confirmed_both"  # both have: the change holds
    WITHDRAWN = "withdrawn"


class FactChanged(Event):
    """Sent by mouth for each step of an amendment, all with the same change_id.
    Nothing changes until status is confirmed_both. Listened to by memory, contract,
    dashboard."""

    name: Literal["fact.changed"] = "fact.changed"
    change_id: str = Field(default_factory=new_id)
    fact_id: str  # the fact it changes
    new_value: str
    status: ChangeStatus = ChangeStatus.PROPOSED
    item: ItemKey | None = None
    proposed_by: Role | None = None
    confirmed_by: list[Role] = []
    said: str | None = None  # the words of this step


class CrewAgent(StrEnum):
    EARS = "ears"
    SCRIBE = "scribe"
    MEMORY = "memory"
    JUDGE = "judge"
    FLOOR = "floor"
    GAWAH = "gawah"
    CLERK = "clerk"
    SENTINEL = "sentinel"


class AgentNote(Event):
    """Sent by any stream: one line of what an agent just did, for the dashboard's agent
    lanes. Listened to by dashboard only. Nothing may depend on it."""

    name: Literal["agent.note"] = "agent.note"
    agent: CrewAgent
    text: str  # a few words, e.g. "found 2 facts about the advance"
    fact_ids: list[str] = []
    line_nos: list[int] = []


AnyEvent = Annotated[
    DealRequested
    | CallStarted
    | CallOpened
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
    | ReplyTimeout
    | WhatsAppMessage
    | FactRecorded
    | FactConflict
    | FactChanged
    | AgentNote,
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
