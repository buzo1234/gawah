from datetime import date

import pytest

from app.memory.normalise import filler_kind, normalise_rupees, parse_rupees, pin_date, stated_total


@pytest.mark.parametrize("said, rupees", [
    ("22 hazaar", [22000]), ("बाईस हज़ार", [22000]), ("२२ हज़ार", [22000]), ("22,000", [22000]), ("22k", [22000]),
    ("₹22,000", [22000]), ("Rs 500", [500]), ("300 rupaye roz", [300]), ("saade teen hazaar", [3500]),
    ("dedh lakh", [150000]), ("pachchees hazaar paanch sau", [25500]), ("13 hazaar 500", [13500]),
    ("do coat chahiye", []), ("10 baje aa jao", []), ("14 kar dete hain", []), ("2BHK flat", []),
])
def test_rupees_are_read_from_the_words(said, rupees):
    assert parse_rupees(said) == rupees


def test_the_model_sets_the_scale_where_the_words_leave_it_open():
    assert normalise_rupees(14000, "14,000 rupees", "Chaliye 14 kar dete hain.") == 14000
    assert normalise_rupees(3000, "3,000 rupees", "To total 14 hazaar mein se 3 advance") == 3000
    assert normalise_rupees(15000, "15,000 rupees", "13 hazaar, last") == 13000  # the words win
    assert normalise_rupees(0, "no advance", "Advance nahi chahiye") == 0
    assert normalise_rupees(None, "after the work", "total 14 hazaar mein se baaki finish pe") is None
    assert stated_total("To total 14 hazaar mein se 3 advance") == 14000


def test_dates_are_pinned_only_when_the_words_agree():
    saturday = date(2026, 11, 21)
    assert pin_date("kal subah de dungi", saturday, None) == date(2026, 11, 22)
    assert pin_date("agle Monday tak", saturday, None) == date(2026, 11, 23)
    assert pin_date("25 November ko", saturday, None) == date(2026, 11, 25)
    assert pin_date("Parson se, Wednesday", saturday, None) is None  # parson is Monday: two days
    assert pin_date("Parson se, Wednesday", saturday, date(2026, 11, 25)) == date(2026, 11, 25)


def test_greetings_and_plain_yeses_need_no_model():
    assert [filler_kind(t, {"ramesh"}) for t in ("Theek hai.", "Ji, done.", "Haan ji", "Theek hai Ramesh ji")] == ["yes"] * 4
    assert [filler_kind(t) for t in ("Ji namaste.", "Hello?")] == ["greeting"] * 2
    assert filler_kind("Haan haan theek hai. Achha, shuru kab se karoge?") is None
