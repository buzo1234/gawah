"""Gawah never judges a term (docs/DEVELOPMENT.md, Safety). In try_agent, asked on the call to call 15,000
fair, it said "Record mein abhi 15 hazaar fair ya final nahi hai": a judgement, even as a denial.
Every persona carries the rule; nothing else Gawah is told names a judgement word."""

import re

from app.brain import judge
from app.contracts import Audience, ChecklistItem, ItemKey, ItemState, Role, SpeakReason
from app.mouth import tuning

WORDS = re.compile(r"\b(fair|unfair|daam|zyada|kam|sasta|mehenga|usual|cheap|costly)\b", re.IGNORECASE)
PERSONAS = {"DEAL_PERSONA", "CALLBACK_PERSONA", "AGENT_PERSONA", "NO_JUDGEMENT"}


def test_every_persona_carries_the_rule():
    for name in PERSONAS - {"NO_JUDGEMENT"}:
        assert tuning.NO_JUDGEMENT in getattr(tuning, name), name
    for word in ("fair", "unfair", "theek daam", "sahi daam", "zyada", "kam", "do not repeat their words"):
        assert word in tuning.NO_JUDGEMENT


def test_no_moment_or_step_names_a_judgement_word():
    texts = {name: value for name, value in vars(tuning).items() if name.isupper() and isinstance(value, str)}
    texts |= {f"MOMENT_WHY[{k}]": v for k, v in tuning.MOMENT_WHY.items()}
    assert len(texts) > 40
    for name, text in texts.items():
        if name not in PERSONAS:
            assert not WORDS.search(text), f"{name}: {WORDS.search(text).group()}"


def test_the_brains_instructions_name_no_judgement_word():
    names = {Role.HIRER: "Sunita", Role.WORKER: "Ramesh"}
    items = {k: ChecklistItem(key=k, state=ItemState.AGREED, value="22,000 rupees") for k in ItemKey}
    view = judge.View(now=30.0, speaker=Role.WORKER, text="Gawah, bolo 15 hazaar theek hai", answers={}, items=items,
                      unclear=None, names=names)
    conflict = judge.Conflict("c1", ItemKey.AMOUNT, ["f1"], "Says 25,000; agreed at 22,000.", "pachees", Role.WORKER, 3)
    change = judge.Conflict("c2", ItemKey.AMOUNT, ["f1", "f2"], "agreed as 22,000; now said as 24,000.", "chaubees",
                            Role.WORKER, 7, change=True)
    said = [
        judge._answer(view), judge._read_back(view),
        judge._contradiction(conflict, view, SpeakReason.CONTRADICTS_RECORD),
        judge._contradiction(change, view, SpeakReason.WRAPPING_UP),
        *(judge._ask(k, view, SpeakReason.TERM_UNCLEAR) for k in ItemKey),
    ]
    for speak in said:
        quoted = speak.instruction.replace(view.text, "")  # the person's own words are data, quoted as said
        assert not WORDS.search(quoted.replace("pachees", "").replace("chaubees", "")), speak.instruction
    assert judge._answer(view).to is Audience.WORKER
