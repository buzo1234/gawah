from datetime import UTC, datetime

import pytest
from contract_fakes import agreed_items

from app.contract import document
from app.contract.document import Bi
from app.contract.pdf import find_chrome, page_count, render_pdf
from app.contracts import ItemKey, Role, TranscriptLine
from fakes import RAMESH, SUNITA
from fakes.replayer import load

HINDI = {
    ItemKey.WORK: "2BHK फ्लैट की पेंटिंग: दीवारों पर 2 कोट, सीलिंग पर 1 कोट, दरवाज़ों और बालकनी की रेलिंग पर एनेमल, जहाँ ज़रूरत हो वहाँ पुट्टी।",
    ItemKey.AMOUNT: "कुल ₹13,000, सिर्फ़ मज़दूरी के। पेंट सुनीता खुद लाएँगी।",
    ItemKey.ADVANCE: "एडवांस ₹3,000, कल सुबह कैश में।",
    ItemKey.DATES: "काम बुधवार को शुरू होगा और अगले सोमवार शाम तक पूरा होगा।",
    ItemKey.LATE_OR_UNFINISHED: "देर हुई तो हर दिन के ₹300 कटेंगे। काम अधूरा छोड़ा तो बाकी पैसा नहीं मिलेगा और एडवांस वापस होगा।",
}


def fixed_document(names=None) -> document.Document:
    """A contract from fixed text: the practice call's terms, with the balance never agreed."""
    items = agreed_items(pending=(ItemKey.BALANCE,))
    bodies = {i.key.value: {"hi": HINDI[i.key], "en": i.value} for i in items if i.value}
    lines = [TranscriptLine(deal_id="d1", **line) for line in load("fixtures/call_two_amounts.json")["lines"]]
    names = names or {Role.HIRER: Bi("सुनीता", "Sunita"), Role.WORKER: Bi("रमेश", "Ramesh")}
    return document.build(
        "d1", {Role.HIRER: SUNITA, Role.WORKER: RAMESH}, names, items, bodies, lines,
        confirmed_at={Role.HIRER: datetime(2026, 11, 21, 11, 32, tzinfo=UTC), Role.WORKER: datetime(2026, 11, 21, 12, 5, tzinfo=UTC)},
        call_ended_at=datetime(2026, 11, 21, 11, 0, tzinfo=UTC), now=datetime(2026, 11, 21, 19, 0, tzinfo=UTC),
    )


def test_the_text_has_everything_a_contract_must_have():
    text = fixed_document().text()
    for expected in (
        "तारीख / Date: 22 नवंबर 2026 / 22 November 2026",  # 19:00 UTC is already the 22nd in India
        "सौदा नंबर / Deal ID: d1",
        "काम देने वाले / Hirer: सुनीता (Sunita), +910000000001",
        "काम करने वाले / Worker: रमेश (Ramesh), +910000000002",
        "2. कुल पैसा / The amount\nकुल ₹13,000, सिर्फ़ मज़दूरी के। पेंट सुनीता खुद लाएँगी।\n13,000 rupees, labour only; the hirer brings the paint\n"
        "(कॉल में 0 मिनट 59 सेकंड पर कहा गया / Said 0 min 59 sec into the call)",
        "4. बाकी पैसा / The balance\nयह बात कॉल पर तय नहीं हुई।\nThis was not agreed on the call.\n\n5.",
        "(कॉल में 2 मिनट 7 सेकंड पर कहा गया / Said 2 min 7 sec into the call)",
        "This is a written record of a spoken agreement made on a recorded call on 21 November 2026. Both people "
        "confirmed these terms separately: Sunita on 21 November 2026 at 5:02 pm, and Ramesh on 21 November 2026 at 5:35 pm.",
        "सुनीता ने 21 नवंबर 2026 को शाम 5:02 बजे और रमेश ने 21 नवंबर 2026 को शाम 5:35 बजे।",
    ):
        assert expected in text, expected
    assert [line[:2] for line in text.splitlines() if line[:2] in {"1.", "2.", "3.", "4.", "5.", "6."}] == ["1.", "2.", "3.", "4.", "5.", "6."]


def test_a_name_never_said_on_the_call_becomes_the_role():
    text = fixed_document(names={Role.HIRER: Bi("सुनीता", "Sunita"), Role.WORKER: None}).text()
    assert "काम करने वाले / Worker: काम करने वाले (Worker), +910000000002" in text
    assert "and Worker on 21 November 2026 at 5:35 pm" in text


@pytest.mark.skipif(find_chrome() is None, reason="needs Chrome to print the PDF")
async def test_the_hindi_contract_prints_to_a_pdf_of_one_or_two_pages(tmp_path):
    doc = fixed_document()
    html = doc.html()
    assert "दरवाज़ों और बालकनी की रेलिंग पर एनेमल" in html and "<script" not in html
    out = tmp_path / "contract.pdf"
    await render_pdf(html, out)
    pdf = out.read_bytes()
    assert pdf.startswith(b"%PDF") and 1 <= page_count(pdf) <= 2
    assert b"Devanagari" in pdf  # a Hindi font was embedded, not boxes from a Latin one


def test_text_from_the_call_cannot_inject_markup():
    doc = fixed_document(names={Role.HIRER: Bi("<script>x</script>", "<b>Sunita</b>"), Role.WORKER: None})
    assert "<script>" not in doc.html() and "<b>Sunita" not in doc.html()
