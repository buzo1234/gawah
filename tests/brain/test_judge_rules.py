"""The rules the practice calls do not reach, on scripted answers and the fake call.
The answers here are written by hand, not recorded."""

from app.brain import Brain, tuning
from app.contracts import (
    CallKind,
    ChecklistUpdated,
    ItemState,
    JudgeSpeak,
    JudgeSpoke,
    Role,
    SpeakReason,
)
from fakes.call import end_call, say, start_call

DEAL = "deal-1"
ITEMS = ["work_agreed", "amount_agreed", "advance_agreed", "balance_when", "dates_agreed", "late_terms"]


class Scripted:
    """Sage2 stand-in: per line, the questions answered yes. None means no answer came."""

    def __init__(self, *lines: set[str] | None) -> None:
        self.lines = lines

    async def open(self, preamble):
        return {}

    async def append(self, seq, text):
        yes = self.lines[seq - 1]
        return None if yes is None else {q: 0.99 for q in yes}

    async def close(self):
        pass


class Values:
    """OpenAI stand-in: every term is settled unless a reply is given for it."""

    def __init__(self, **replies) -> None:
        self.replies, self.asked = replies, []

    async def lookup(self, kind, item, transcript, at_line):
        self.asked.append((kind, item.value if item else None, at_line))
        name = f"{kind}_{item.value}" if item else kind
        if name in self.replies:
            reply = self.replies[name]
            return reply.pop(0) if isinstance(reply, list) else reply
        return {"value": f"the {item.value}", "source_text": "said so", "line_no": at_line} if kind == "value" else None


class Call:
    def __init__(self, bus, script: Scripted, values: Values | None = None, mode="live", mouth=False) -> None:
        self.bus, self.values = bus, values or Values()
        self.speaks: list[JudgeSpeak] = []
        self.checklists: list[ChecklistUpdated] = []
        self.clock, self.line_no = 0.0, 0
        Brain(bus, mode, lambda started: (script, self.values))

        async def on_speak(event: JudgeSpeak) -> None:
            self.speaks.append(event)
            if mouth == "drops":  # the moment passes and nothing is said
                bus.publish(JudgeSpoke(deal_id=DEAL, text="", speak_id=event.event_id))
            elif mouth:  # says it at once, and takes two seconds
                bus.publish(JudgeSpoke(deal_id=DEAL, text="...", speak_id=event.event_id, end=self.clock + 2.0))

        async def on_checklist(event: ChecklistUpdated) -> None:
            self.checklists.append(event)

        bus.subscribe(JudgeSpeak, on_speak)
        bus.subscribe(ChecklistUpdated, on_checklist)
        start_call(bus, DEAL)

    async def say(self, text="haan theek hai", speaker=Role.HIRER, takes=4.0) -> None:
        self.line_no += 1
        start, self.clock = self.clock, self.clock + takes
        say(self.bus, DEAL, speaker, text, start=start, end=self.clock, line_no=self.line_no)
        await self.bus.drain()

    @property
    def spoken(self) -> list[tuple]:
        return [(s.after_line, s.reason.value, s.item.value if s.item else None) for s in self.speaks]

    def item(self, key: str):
        return next(i for i in self.checklists[-1].items if i.key == key)


async def test_read_back_once_when_nothing_is_pending(bus):
    call = Call(bus, Scripted(set(ITEMS), set(ITEMS), {*ITEMS, "wrapping_up"}, {*ITEMS, "wrapping_up"}, {*ITEMS, "wrapping_up"}))
    for _ in range(5):
        await call.say(takes=8.0)
    assert call.spoken == [(3, "wrapping_up", None)]
    speak = call.speaks[0]
    assert speak.to == "both"
    assert speak.instruction.startswith("They are about to hang up. Read back the agreed terms and ask Sunita and Ramesh to confirm them.")
    for value in ("the work", "the amount", "the advance", "the balance", "the dates", "the late_or_unfinished"):
        assert f": {value}" in speak.instruction


async def test_no_read_back_while_an_item_is_pending(bus):
    most = set(ITEMS) - {"late_terms"}
    call = Call(bus, Scripted(most, {*most, "wrapping_up"}, {*most, "wrapping_up"}))
    for _ in range(3):
        await call.say(takes=20.0)
    assert call.spoken == [(2, "wrapping_up", "late_or_unfinished")]


async def test_question_answered_then_read_back(bus):
    """With a mouth: the skipped balance is asked once, they answer, the call ends in a read-back."""
    some = {"work_agreed", "amount_agreed", "advance_agreed"}
    call = Call(
        bus,
        Scripted(
            some,
            {*some, "balance_skipped"},  # 2: moved on to dates
            {*some, "balance_skipped"},
            {*some, "balance_when"},  # 4: "kaam khatam hone pe"
            set(ITEMS),
            {*ITEMS, "wrapping_up"},
        ),
        mouth=True,
    )
    for _ in range(6):
        await call.say()
    assert call.spoken == [(2, "term_unclear", "balance"), (6, "wrapping_up", None)]
    assert call.item("balance").state is ItemState.AGREED


async def test_two_figures_settled_after_the_judge_asks(bus):
    settled = {"value": "13,000 rupees", "source_text": "13 hi hai", "line_no": 4}
    values = Values(
        conflict={"item": "amount", "figures": ["13,000 rupees", "14,000 rupees"]},
        value_amount=[{"value": "13,000 rupees, labour only", "source_text": "13 hazaar", "line_no": 1}, {"value": None}, settled],
    )
    call = Call(
        bus,
        Scripted(
            {"amount_agreed"},
            {"conflicting_figures"},  # 2: 14 said; Sage2 drops amount_agreed
            {"conflicting_figures", "amount_agreed"},  # 3: too soon after the question to look
            {"conflicting_figures", "amount_agreed"},  # 4: looked, model says still open
            {"conflicting_figures", "amount_agreed"},
            {"conflicting_figures", "amount_agreed"},  # 6: looked again, settled
            {"conflicting_figures", "amount_agreed"},
        ),
        values,
        mouth=True,
    )
    await call.say()
    await call.say()
    assert call.spoken == [(2, "conflicting_figures", "amount")]
    assert call.item("amount").state is ItemState.PENDING
    assert call.item("amount").note == "two figures said: 13,000 rupees and 14,000 rupees"
    for _ in range(5):
        await call.say()
    amount = call.item("amount")
    assert (amount.state, amount.value, amount.note) == (ItemState.AGREED, "13,000 rupees", None)
    assert [at for kind, item, at in values.asked if (kind, item) == ("value", "amount")] == [1, 4, 6]
    assert call.spoken == [(2, "conflicting_figures", "amount")], "settled, so it is not asked again"


async def test_two_figures_without_the_model_still_asks(bus):
    call = Call(bus, Scripted({"amount_agreed", "advance_agreed"}, {"advance_agreed", "conflicting_figures"}), Values(conflict=None))
    await call.say()
    await call.say()
    assert call.spoken == [(2, "conflicting_figures", "amount")]
    assert call.speaks[0].instruction == "Two different figures were said for the total amount. Ask Sunita and Ramesh which one is right."
    assert call.item("amount").note == "two different figures said"


async def test_two_figures_for_no_term_anyone_can_name_wipe_nothing(bus):
    # Dry run, 21 Nov: the model's lookup timed out, Sage2 still said the amount was agreed,
    # and a guess of "amount" emptied the agreed 22,000 for the rest of the deal.
    call = Call(bus, Scripted({"amount_agreed", "advance_agreed"}, {"amount_agreed", "advance_agreed", "conflicting_figures"}), Values(conflict=None))
    await call.say()
    await call.say()
    assert call.spoken == []
    assert call.item("amount").state is ItemState.AGREED and call.item("amount").value == "the amount"


async def test_minimum_gap_between_interruptions(bus):
    call = Call(
        bus,
        Scripted({"advance_agreed", "balance_skipped"}, *[{"advance_agreed", "balance_skipped", "conflicting_figures"}] * 6),
        Values(conflict={"item": "advance", "figures": ["3,000 rupees", "4,000 rupees"]}),
        mouth=True,
    )
    for _ in range(7):
        await call.say(takes=4.0)
    # Asked about the balance after line 1 (4s), finished at 6s. The advance conflict shows
    # at line 2 (8s) and has to wait until 6 + MIN_GAP_S.
    assert tuning.MIN_GAP_S == 15.0
    assert call.spoken == [(1, "term_unclear", "balance"), (6, "conflicting_figures", "advance")]


async def test_one_at_a_time_until_judge_spoke_or_timeout(bus):
    both = {"topic_left_unclear", "addressed_gawah"}
    call = Call(bus, Scripted(both, both, both, both, both), Values(unclear={"item": "dates"}))  # no mouth
    for _ in range(5):
        await call.say("Gawah, suno", takes=4.0)
    assert tuning.SPEAK_TIMEOUT_S == 12.0
    # Answers at 4s; nothing more until 16s, then the next thing in line.
    assert call.spoken == [(1, "addressed_directly", None), (4, "addressed_directly", None)]
    assert all(s.to == "hirer" for s in call.speaks)


async def test_a_question_the_mouth_dropped_neither_holds_up_nor_uses_up_the_gap(bus):
    call = Call(
        bus,
        Scripted({"advance_agreed", "balance_skipped"}, {"advance_agreed", "balance_skipped", "conflicting_figures"}),
        Values(conflict={"item": "advance", "figures": ["3,000 rupees", "4,000 rupees"]}),
        mouth="drops",
    )
    await call.say(takes=4.0)
    await call.say(takes=4.0)
    # Without the empty judge.spoke the conflict would wait SPEAK_TIMEOUT_S, then MIN_GAP_S.
    assert call.spoken == [(1, "term_unclear", "balance"), (2, "conflicting_figures", "advance")]


async def test_answering_someone_does_not_use_up_the_gap(bus):
    call = Call(
        bus, Scripted({"addressed_gawah"}, {"advance_agreed", "balance_skipped"}), mouth=True
    )
    await call.say("Gawah, sun rahe ho?", speaker=Role.WORKER)
    await call.say()
    assert call.spoken == [(1, "addressed_directly", None), (2, "term_unclear", "balance")]
    assert call.speaks[0].to == "worker"
    assert 'Ramesh spoke to you directly and said: "Gawah, sun rahe ho?"' in call.speaks[0].instruction


async def test_dodged_question_asks_about_the_term_the_model_names(bus):
    values = Values(unclear={"item": "dates"})
    call = Call(bus, Scripted(set(), {"topic_left_unclear"}, {"topic_left_unclear"}, {"topic_left_unclear"}), values)
    for _ in range(4):
        await call.say(takes=20.0)
    assert call.spoken == [(2, "term_unclear", "dates")]
    assert call.speaks[0].to == "worker"
    assert values.asked.count(("unclear", None, 2)) == 1 and len(values.asked) == 1, "looked up once, not on every line"


async def test_wrapup_mode_only_speaks_at_wrap_up(bus):
    script = Scripted(
        {"addressed_gawah", "advance_agreed", "balance_skipped", "topic_left_unclear"},
        {"advance_agreed", "balance_skipped", "conflicting_figures"},
        {"balance_skipped", "conflicting_figures", "wrapping_up"},
    )
    call = Call(bus, script, Values(conflict={"item": "advance", "figures": ["3,000 rupees", "4,000 rupees"]}), mode="wrapup")
    for _ in range(3):
        await call.say("Gawah?")
    assert [s.reason for s in call.speaks] == [SpeakReason.WRAPPING_UP]
    assert call.speaks[0].after_line == 3
    assert call.item("advance").note == "two figures said: 3,000 rupees and 4,000 rupees", "the checklist is kept in every mode"


async def test_sage_going_quiet_keeps_the_checklist_and_says_nothing_new(bus):
    call = Call(bus, Scripted({"work_agreed", "addressed_gawah"}, None, None))
    for _ in range(3):
        await call.say(takes=20.0)
    assert call.spoken == [(1, "addressed_directly", None)], "a line with no answer is not taken as speaking to Gawah"
    assert call.item("work").state is ItemState.AGREED


async def test_agreed_items_latch_and_a_missing_value_is_tried_again(bus):
    values = Values(value_work=[{"value": None}, {"value": "paint the flat", "source_text": "paint", "line_no": 2}])
    call = Call(bus, Scripted({"work_agreed"}, set(), set(), set()), values)
    for _ in range(4):
        await call.say()
    work = call.item("work")
    assert (work.state, work.value, work.line_no) == (ItemState.AGREED, "paint the flat", 2)
    assert [at for _, _, at in values.asked] == [1, 3]
    assert all(len(update.items) == 6 for update in call.checklists)


async def test_call_backs_and_other_deals_are_ignored(bus):
    seen = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated)):
            seen.append(event)

    bus.subscribe_all(collect)
    Brain(bus, "live", lambda started: (Scripted({"addressed_gawah", "wrapping_up"}), Values()))
    start_call(bus, "deal-2", kind=CallKind.CALLBACK)
    say(bus, "deal-2", Role.HIRER, "Gawah, haan sahi hai", end=3.0, line_no=1)
    say(bus, "deal-3", Role.HIRER, "a line for a call that never started", end=3.0, line_no=1)
    end_call(bus, "deal-2", kind=CallKind.CALLBACK)
    await bus.drain()
    assert seen == []


async def test_nothing_is_said_after_the_call_ends(bus):
    call = Call(bus, Scripted(set(ITEMS), {*ITEMS, "wrapping_up"}))
    await call.say()
    end_call(bus, DEAL)
    await call.say()
    assert call.spoken == []
