import pytest
from contract_fakes import FakeWriter, agreed_items, answer_for

from app.contract.check import days, numbers, problems
from app.contract.document import Bi
from app.contract.writer import DraftRejected, write_draft
from app.contracts import Role, TranscriptLine

ITEMS = agreed_items()
GOOD = answer_for(ITEMS)


def with_term(key: str, hi: str | None = None, en: str | None = None) -> dict:
    term = GOOD["terms"][key]
    return GOOD["terms"] | {key: {"hi": hi or term["hi"], "en": en or term["en"]}}


def test_figures_are_read_the_same_however_they_are_written():
    for text in ("24,000 rupees", "₹24000", "२४,००० रुपये", "24 hazaar", "24k", "24 हज़ार", "24 हजार"):
        assert numbers(text) == {24000}, text
    assert numbers("1.5 lakh") == {150000}
    assert numbers("2BHK, 5 kamre, 9 baje") == {2, 5, 9}
    assert days("Monday se शुक्रवार tak, 23 Nov") == {"monday", "friday", "november"}
    assert days("it may be late") == set()


def test_text_that_restates_the_checklist_passes():
    assert problems(ITEMS, GOOD["terms"], GOOD["summary_hi"]) == []


def test_an_amount_that_is_not_in_the_checklist_is_rejected():
    terms = with_term("balance", en="The remaining 10,000 rupees on the day the work is finished")
    assert problems(ITEMS, terms, GOOD["summary_hi"]) == [
        "balance.en has the figure 10000, which is not in the agreed terms"
    ]
    # 14,000 was said on the call but 13,000 is what was agreed
    summary = GOOD["summary_hi"] + " कुल ₹14,000"
    assert problems(ITEMS, GOOD["terms"], summary) == [
        "summary_hi has the figure 14000, which is not in the agreed terms"
    ]


def test_an_agreed_amount_or_day_left_out_is_rejected():
    assert problems(ITEMS, with_term("amount", hi="सिर्फ मज़दूरी, पेंट सुनीता लाएँगी"), GOOD["summary_hi"]) == [
        "amount.hi is missing the figure 13000; write it in digits"
    ]
    assert problems(ITEMS, with_term("dates", en="Start on Wednesday, finish in 6 days"), GOOD["summary_hi"]) == [
        "dates.en is missing the day or month monday",
        "dates.en has the figure 6, which is not in the agreed terms",
    ]
    assert problems(ITEMS, with_term("dates", hi="बुधवार को शुरू, अगले सोमवार शाम तक पूरा"), GOOD["summary_hi"]) == []


def test_amounts_in_words_the_wrong_script_and_a_long_summary_are_rejected():
    found = problems(
        ITEMS,
        with_term("advance", hi="3,000 rupees cash, kal subah", en="3,000 rupees and तीन हज़ार"),
        " ".join(["सौदा"] * 90),
    )
    assert found == [
        "advance.hi is in the wrong script",
        "advance.en is in the wrong script",
        "advance.en spells an amount in words; write figures in digits",
        "summary_hi has 90 words; it must have 44 to 55",
    ]


LINES = [
    TranscriptLine(deal_id="d", speaker=Role.WORKER, text="Hello, Sunita madam? Main painter bol raha hoon.", start=0, end=4),
]


async def test_a_rejected_draft_is_retried_with_the_problems_listed(caplog):
    bad = answer_for(ITEMS, terms=with_term("amount", en="13,000 rupees for labour, about 20,000 with paint"))
    writer = FakeWriter(ITEMS, answers=[bad])
    draft = await write_draft(writer, "d", ITEMS, LINES)
    assert len(writer.calls) == 2
    assert "deal=d draft rejected by the check: amount.en has the figure 20000" in caplog.text
    assert "amount.en has the figure 20000, which is not in the agreed terms" in writer.calls[1]
    assert draft.terms == GOOD["terms"]


async def test_three_rejected_drafts_and_it_gives_up():
    bad = answer_for(ITEMS, summary_hi="कुल ₹99,000 " * 25)
    writer = FakeWriter(ITEMS, answers=[bad] * 5)
    with pytest.raises(DraftRejected, match="99000"):
        await write_draft(writer, "d", ITEMS, LINES)
    assert len(writer.calls) == 3


async def test_a_name_is_used_only_if_it_was_said_on_the_call():
    draft = await write_draft(FakeWriter(ITEMS), "d", ITEMS, LINES)
    assert draft.names == {Role.HIRER: Bi("सुनीता", "Sunita"), Role.WORKER: None}  # Ramesh never said his name


async def test_the_place_of_work_is_used_only_if_it_was_said_on_the_call():
    indirapuram = answer_for(ITEMS, place={"hi": "इंदिरापुरम", "en": "Indirapuram"})
    draft = await write_draft(FakeWriter(ITEMS, answers=[indirapuram]), "d", ITEMS, LINES)
    assert draft.place is None  # nobody said it on this call
    said = [*LINES, TranscriptLine(deal_id="d", speaker=Role.HIRER, text="Mera flat Indirapuram mein hai.", start=5, end=8)]
    draft = await write_draft(FakeWriter(ITEMS, answers=[indirapuram]), "d", ITEMS, said)
    assert draft.place == Bi("इंदिरापुरम", "Indirapuram")
