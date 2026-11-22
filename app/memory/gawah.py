"""What Gawah says on a deal call, as the Scribe hears it.

Gawah's words are context, never facts: the Scribe's model sees them among the lines before
the new one. When Gawah asks both to confirm a value one of them said, a person's yes right
after it agrees that value for them, as a yes to the other person's offer would. Which values
the question named comes from the judge.speak it answers (its fact_ids), so nothing here reads
Gawah's words for a term or a figure.
"""

from dataclasses import dataclass, field

from app.contracts import FactKind, FactStatus, ItemKey, JudgeSpeak, JudgeSpoke, TranscriptLine
from app.memory import echo
from app.memory.book import DealBook, GawahTurn
from app.memory.normalise import answers_yes, filler_kind

ANSWER_LINES = 4  # a person's first word this many lines after Gawah's question still answers it
KEEP = 50  # judge.speaks held while waiting for the mouth to say them


@dataclass
class Reply:
    after_line: int  # the line Gawah spoke after
    asked: set[ItemKey]  # the terms Gawah's question named
    agreed: set[ItemKey] = field(default_factory=set)  # the terms the yes agreed


class Gawah:
    def __init__(self, memory) -> None:
        self.m = memory
        self._asked: dict[str, JudgeSpeak] = {}

    async def on_speak(self, event: JudgeSpeak) -> None:
        self.asked(event)

    async def on_spoke(self, event: JudgeSpoke) -> None:
        self.spoke(event)

    def asked(self, event: JudgeSpeak) -> None:
        self._asked[event.event_id] = event
        while len(self._asked) > KEEP:
            self._asked.pop(next(iter(self._asked)))

    def spoke(self, event: JudgeSpoke) -> None:
        speak = self._asked.pop(event.speak_id or "", None)
        if not event.text.strip():
            return  # dropped unsaid
        deal = self.m.book.deal(event.deal_id)
        call_no = deal.last_call_no
        heard = [n for (c, n) in deal.lines if c == call_no]
        # Cut off, the value may not have been heard: a yes to it is no yes to the value.
        named = list(speak.fact_ids) if speak and not event.interrupted else []
        deal.turns.append(GawahTurn(call_no, max(heard, default=0), " ".join(event.text.split()), named))

    @staticmethod
    def context(deal: DealBook, line: TranscriptLine, since: int) -> list[tuple[int, str]]:
        """Gawah's words between line `since` and the new line, each with the line it came after."""
        return [(t.after_line, t.text) for t in deal.turns
                if t.call_no == line.call_no and since <= t.after_line < line.line_no]

    def answer(self, deal: DealBook, line: TranscriptLine, received: float) -> Reply | None:
        """The line is the speaker's answer to Gawah's last turn, a question naming values said on
        the call: the terms it named, and those its yes agreed. None when it answers no such turn:
        a turn that named no value changes nothing about how the line is read."""
        turn = next((t for t in reversed(deal.turns) if t.call_no == line.call_no and t.after_line < line.line_no), None)
        if turn is None or not turn.fact_ids or line.speaker in turn.answered or line.line_no - turn.after_line > ANSWER_LINES:
            return None
        facts = [f for i in turn.fact_ids if (f := deal.latest.get(i)) and f.kind == FactKind.TERM and f.item]
        names = {n.lower() for n in deal.names.values()}
        if not facts or filler_kind(line.text, names) == "greeting":
            return None  # "dhanyavaad": not an answer yet
        turn.answered.add(line.speaker)
        reply = Reply(turn.after_line, {f.item for f in facts})
        if not answers_yes(line.text, names) or echo.doubts(line.text):
            return reply  # a no, a hedge or a question back: nothing agreed
        for fact in facts:
            if fact.status != FactStatus.SAID:
                continue
            reply.agreed.add(fact.item)
            if fact.said_by is None or line.speaker in (fact.said_by, *fact.agreed_by):
                continue  # their own words, said again: the other person's yes is what agrees it
            self.m.scribe.upgrade(deal, fact, line, received, None)
        return reply
