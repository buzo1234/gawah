import hashlib
import re
from datetime import UTC, datetime

import pytest
from contract_fakes import agreed_items

from app.contract import document, page
from app.contract.document import Bi
from app.contract.pdf import find_chrome, page_count, render_pdf
from app.contract.terms import resolve
from app.contract.trigger import Call
from app.contracts import CallEnded, ChecklistItem, ItemKey, ItemState, Role, TranscriptLine
from fakes import RAMESH, SUNITA
from fakes.replayer import load

HINDI = {
    ItemKey.WORK: "2BHK फ्लैट की पेंटिंग: दीवारों पर 2 कोट, सीलिंग पर 1 कोट, दरवाज़ों और बालकनी की रेलिंग पर एनेमल, जहाँ ज़रूरत हो वहाँ पुट्टी।",
    ItemKey.AMOUNT: "कुल ₹13,000, सिर्फ़ मज़दूरी के। पेंट सुनीता खुद लाएँगी।",
    ItemKey.ADVANCE: "एडवांस ₹3,000, कल सुबह कैश में।",
    ItemKey.BALANCE: "जिस दिन काम पूरा होगा, उसी दिन सुनीता काम देखकर बाकी पैसे देंगी।",
    ItemKey.DATES: "काम बुधवार को शुरू होगा और अगले सोमवार शाम तक पूरा होगा।",
    ItemKey.LATE_OR_UNFINISHED: "देर हुई तो हर दिन के ₹300 कटेंगे। काम अधूरा छोड़ा तो बाकी पैसा नहीं मिलेगा और एडवांस वापस होगा।",
}
NAMES = {Role.HIRER: Bi("सुनीता", "Sunita"), Role.WORKER: Bi("रमेश", "Ramesh")}
PRINTS = {Role.HIRER: hashlib.sha256(b"hirer").hexdigest(), Role.WORKER: hashlib.sha256(b"worker").hexdigest()}


LINES = {(1, line["line_no"]): TranscriptLine(deal_id="d1", **line) for line in load("fixtures/call_two_amounts.json")["lines"]}
CALL_1 = Call(ended=CallEnded(deal_id="d1", duration=145.0, ts=datetime(2026, 11, 21, 11, 0, tzinfo=UTC)))


def fixed_document(pending=(), items=None, call=CALL_1, fingerprints=PRINTS, **changes) -> document.Document:
    """An agreement from fixed text: the practice call's terms, with nothing asked of a model."""
    items = items or agreed_items(pending=pending)
    checklist = {i.key: (i, 1) for i in items if i.state is ItemState.AGREED}
    facts = dict(
        deal_id="d1", people={Role.HIRER: SUNITA, Role.WORKER: RAMESH}, names=NAMES, place=None,
        terms=resolve(checklist, {}, [], {}, LINES, {}),
        bodies={i.key.value: {"hi": HINDI[i.key], "en": i.value} for i in items if i.value},
        confirmed_at={Role.HIRER: datetime(2026, 11, 21, 11, 32, tzinfo=UTC), Role.WORKER: datetime(2026, 11, 21, 12, 5, tzinfo=UTC)},
        confirmed_said={Role.HIRER: "haan sab sahi hai", Role.WORKER: None},
        calls={1: call} if call else {}, fingerprints={(1, role): digest for role, digest in fingerprints.items()},
        now=datetime(2026, 11, 21, 19, 0, tzinfo=UTC),
    )
    return document.build(**(facts | changes))


def test_the_text_has_everything_the_agreement_must_have():
    text = fixed_document().text()
    for expected in (
        "काम का अनुबंध\nWORK AGREEMENT\nरिकॉर्ड की गई फ़ोन कॉल पर बोलकर हुए समझौते का लिखित रिकॉर्ड\n"
        "Written record of an agreement made by voice on a recorded call",
        "संदर्भ संख्या / Reference no.: GW-D1\nसंस्करण / Version: संस्करण 1 / Version 1\n"
        "तारीख / Date: 22 नवंबर 2026 / 22 November 2026\n\n",  # 19:00 UTC is the 22nd in India
        "पहला पक्ष (काम देने वाले) / First party (the hirer): सुनीता (Sunita), फ़ोन / phone +910000000001",
        "दूसरा पक्ष (काम करने वाले) / Second party (the worker): रमेश (Ramesh), फ़ोन / phone +910000000002",
        "2. कीमत और उसमें क्या शामिल है / The price and what it covers  [कॉल / call 1, 0:59]\n"
        "कुल ₹13,000, सिर्फ़ मज़दूरी के। पेंट सुनीता खुद लाएँगी।\n13,000 rupees, labour only; the hirer brings the paint",
        "3. भुगतान कब और कैसे / Payment schedule\n- एडवांस / Advance: ₹3,000  [कॉल / call 1, 1:10]\n",
        "- बाकी पैसा / Balance: बाकी रकम / The rest  [कॉल / call 1, 1:15]\n",
        "5. देर हुई या काम अधूरा रहा तो / If the work is late or left unfinished  [कॉल / call 1, 2:07]",
        "6. जो बातें तय नहीं हुईं / What was not agreed\n",
        "All six were agreed on the call.",
        "Confirmed by voice on a separate call with Gawah\n21 नवंबर 2026 को शाम 5:02 बजे / 21 November 2026 at 5:02 pm IST\nकहा / Said: “haan sab sahi hai”",
        "21 नवंबर 2026 को शाम 5:35 बजे / 21 November 2026 at 5:35 pm IST\n\nगवाह / WITNESS",  # no words, so no "Said" line
        "Gawah is an AI witness. It was on the call, and recorded it after both people agreed to the recording.",
        "Call 1 started on 21 November 2026 at 4:27 pm IST and lasted 2 min 25 sec.",
        f"कॉल 1 · पहले पक्ष की आवाज़ / Call 1 · First party's audio: {PRINTS[Role.HIRER]}",
        "This document is a written record of a spoken agreement, confirmed separately by both people.",
        "It was not drafted by a lawyer and is not on stamp paper.",
        "If either person disagrees later, they can ask Gawah for the recording of any term.",
    ):
        assert expected in text, expected
    assert [line[:2] for line in text.splitlines() if line[:2] in {"1.", "2.", "3.", "4.", "5.", "6."}] == ["1.", "2.", "3.", "4.", "5.", "6."]


def test_it_never_claims_legal_force_or_adds_standard_clauses():
    doc = fixed_document()
    for words in ("legally binding", "enforceable", "valid in court", "jurisdiction", "arbitration", "governing law",
                  "warranty", "liability", "कानूनी", "अदालत"):
        assert words not in doc.text().lower() and words not in page.html(doc).lower(), words


def test_what_was_not_agreed_is_listed_and_left_out_of_the_payment_table():
    text = fixed_document(pending=(ItemKey.BALANCE, ItemKey.DATES)).text()
    assert "4. काम की तारीखें / The dates\nयह बात कॉल पर तय नहीं हुई।\nThis was not agreed on the call.\n" in text
    assert "- एडवांस / Advance: ₹3,000" in text and "Balance:" not in text
    assert "These were not agreed on the call: when the balance is paid and against what; the start and finish dates." in text
    neither = fixed_document(pending=(ItemKey.ADVANCE, ItemKey.BALANCE)).text()
    assert "3. भुगतान कब और कैसे / Payment schedule\nयह बात कॉल पर तय नहीं हुई।\nThis was not agreed on the call.\n" in neither


def test_a_payment_amount_is_shown_only_when_the_checklist_states_exactly_one():
    def amount(key: ItemKey, value: str) -> str:
        items = [i if i.key is not key else ChecklistItem(key=key, state=ItemState.AGREED, value=value) for i in agreed_items()]
        doc = fixed_document(items=items)
        return next(p.amount.en for p in doc.clauses[2].payments if p.label.en == key.value.capitalize())

    assert amount(ItemKey.ADVANCE, "8,000 rupees by GPay on Monday 23 November 2026") == "₹8,000"
    assert amount(ItemKey.ADVANCE, "Rs 150000 before work starts") == "₹1,50,000"
    assert amount(ItemKey.ADVANCE, "half the price, before work starts") == "As stated"
    assert amount(ItemKey.ADVANCE, "3,000 rupees tomorrow and 2,000 rupees on Friday") == "As stated"
    assert amount(ItemKey.BALANCE, "on Friday 27 November 2026, after the work is checked") == "The rest"  # 2026 is not money
    assert amount(ItemKey.BALANCE, "10,000 rupees on the day the work is finished") == "₹10,000"


def test_names_a_place_and_recordings_appear_only_when_they_exist():
    bare = fixed_document(names={Role.HIRER: NAMES[Role.HIRER]}, call=None, fingerprints={}, confirmed_said={}).text()
    assert "दूसरा पक्ष (काम करने वाले) / Second party (the worker): फ़ोन / phone +910000000002" in bare
    for absent in ("Place of work", "SHA-256", "कहा / Said", "Call 1 "):
        assert absent not in bare, absent
    placed = fixed_document(place=Bi("इंदिरापुरम", "Indirapuram")).text()
    assert "काम की जगह / Place of work: इंदिरापुरम (Indirapuram)" in placed


@pytest.mark.skipif(find_chrome() is None, reason="needs Chrome to print the PDF")
async def test_the_hindi_agreement_prints_to_a_pdf_of_one_or_two_pages(tmp_path):
    html = page.html(fixed_document(place=Bi("इंदिरापुरम", "Indirapuram")))
    assert "दरवाज़ों और बालकनी की रेलिंग पर एनेमल" in html and "<script" not in html
    assert 'counter(page) " of " counter(pages)' in html and "संदर्भ / Ref. GW-D1" in html  # the footer on every page
    out = tmp_path / "contract.pdf"
    await render_pdf(html, out)
    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF") and 1 <= page_count(pdf) <= 2
    assert b"Devanagari" in pdf  # a Hindi font was embedded, not boxes from a Latin one


def test_text_from_the_call_cannot_inject_markup():
    doc = fixed_document(
        names={Role.HIRER: Bi("<script>x</script>", "<b>Sunita</b>"), Role.WORKER: None},
        place=Bi("<img src=x>", "<i>here</i>"), confirmed_said={Role.HIRER: "</p><script>y</script>", Role.WORKER: None},
        deal_id='x"; } body { display: none; } @page { content: "',
    )
    html = page.html(doc)
    for injected in ("<script>", "<b>Sunita", "<img", "<i>here"):
        assert injected not in html, injected
    assert re.fullmatch(r"[A-Z0-9-]+", doc.reference)  # nothing that can end the footer's CSS string
