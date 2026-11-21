from datetime import date

import pytest

from app.memory.dates import pin_date
from app.memory.normalise import filler_kind, normalise_rupees, parse_rupees, stated_total


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


# ---------- Hindi number words (cause 1) ----------

from app.memory.dates import Day, date_parts, meets  # noqa: E402
from app.memory.normalise import opens_with_yes  # noqa: E402
from app.memory.number_words import DEVANAGARI, ENGLISH, ROMAN, table  # noqa: E402


@pytest.mark.parametrize("words", [ROMAN, DEVANAGARI], ids=["roman", "devanagari"])
def test_every_number_from_one_to_ninety_nine_has_a_word(words):
    spelt = table(words)
    assert set(spelt.values()) == set(range(1, 100))
    for word, n in spelt.items():
        assert parse_rupees(f"{word} hazaar") == [n * 1000], word
        assert parse_rupees(f"{word} सौ रुपये") == [n * 100], word


@pytest.mark.parametrize("said, rupees", [
    ("adtees hazaar", [38000]), ("अड़तीस हज़ार", [38000]), ("अड़तीस हज़ार", [38000]),  # composed and decomposed ड़ ़
    ("pachees sau", [2500]), ("पच्चीस सौ", [2500]), ("ek lakh bees hazaar", [120000]),
    ("एक लाख बीस हज़ार", [120000]), ("38 hazaar paanch sau", [38500]), ("ninyaanave hazaar", [99000]),
    ("saade chaar sau", [450]), ("साढ़े तीन हज़ार", [3500]), ("dedh hazaar", [1500]), ("dhai sau", [250]),
    ("ढाई लाख", [250000]), ("sava do lakh", [225000]), ("सवा लाख", [125000]), ("paune do hazaar", [1750]),
    ("पौने तीन लाख", [275000]), ("pauna hazaar", [750]), ("twenty five thousand", [25000]),
    ("ट्वेंटी थाउज़ंड", [20000]), ("1.5 lakh", [150000]), ("Rs. 700 roz", [700]),
    ("tera kaam chhota hai", []), ("bees hazaar do mujhe", [20000]), ("sattar log", []),
])
def test_number_words_and_their_combinations(said, rupees):
    assert parse_rupees(said) == rupees


# ---------- lists of figures (cause 3) ----------

@pytest.mark.parametrize("said, rupees", [
    ("बाईस हज़ार, पाँच एडवांस", [22000]),  # the 5 is the advance, said without its unit
    ("total athais hazaar, chaar advance, baaki baad mein", [28000]),
    ("22 hazaar aur 5 hazaar", [22000, 5000]),
    ("बाईस हज़ार और पाँच सौ", [22000, 500]),
    ("bees hazaar paanch advance", [20000]),
    ("13 hazaar 500", [13500]),  # a trailing hundreds figure is still part of it
])
def test_figures_in_a_list_stay_apart(said, rupees):
    assert parse_rupees(said) == rupees


def test_a_total_in_a_list_is_only_the_total_and_the_bare_figure_takes_the_models_scale():
    line = "तो फाइनल टोटल बाईस हज़ार, पाँच एडवांस, सात बीच में, और दस काम के बाद।"
    assert stated_total(line) == 22000
    assert normalise_rupees(5000, "5,000 rupees", line) == 5000
    assert normalise_rupees(7000, "7,000 rupees", line) == 7000


# ---------- the danda (cause 2) and a yes that opens a line (cause 4) ----------

def test_a_yes_ending_in_a_danda_is_a_plain_yes():
    assert [filler_kind(t) for t in ("ठीक है।", "पक्का।", "हाँ जी।", "जी, ठीक है।", "ठीक है॥")] == ["yes"] * 5
    assert filler_kind("नमस्ते जी।") == "greeting"
    assert filler_kind("ठीक है। एडवांस कितना?") is None


def test_a_line_that_opens_with_a_firm_yes_and_goes_on():
    assert opens_with_yes("Chalo theek hai. To Wednesday subah aa jao.")
    assert opens_with_yes("ठीक है। और देर हुई तो?")
    assert opens_with_yes("Done, Meena ji. Ab kapda dekh lo.", {"meena"})
    assert not opens_with_yes("Haan. Advance kitna?")  # "haan" alone can mean "I hear you"
    assert not opens_with_yes("Theek hai.")  # nothing after it: that is a plain yes
    assert not opens_with_yes("Theek hai 300 ki jagah 200 kar do")


# ---------- dates: meeting days (cause 5), start and finish (cause 6) ----------

SAT = date(2026, 11, 21)


def test_a_day_of_the_month_is_the_next_one_to_come():
    assert pin_date("bees tarikh tak", SAT, None) == date(2026, 12, 20)
    assert pin_date("पच्चीस तारीख को", SAT, None) == date(2026, 11, 25)
    assert pin_date("28th tak", SAT, None) is None  # "28th" with no month or tarikh is not a day
    assert pin_date("28 tarikh", SAT, None) == date(2026, 11, 28)


@pytest.mark.parametrize("said, parts", [
    ("Monday se shuru, Friday tak khatam", {"start": "Mon", "finish": "Fri"}),
    ("अगले सोमवार से शुरू, शुक्रवार तक फिनिश।", {"start": "Mon", "finish": "Fri"}),
    ("bees tarikh tak ho jayega", {"finish": "2026-12-20"}),
    ("पंद्रह तारीख से पहले हो जाएगा।", {"finish": "2026-12-15"}),  # "se pehle" is before: a finish
    ("kal se kaam start karo", {"start": "2026-11-22"}),
    ("start 25 November, finish by 2 December", {"start": "2026-11-25", "finish": "2026-12-02"}),
    ("Monday ko milte hain", {}),
    ("Friday tak, aur 15 tarikh se pehle pakka", {}),  # two finishes in one breath: neither is pinned
])
def test_start_and_finish_are_read_apart(said, parts):
    got = date_parts(said, SAT)
    assert {p: (d.day.strftime("%a") if d.weekday_only else str(d.day)) for p, d in got.items()} == parts


def test_a_weekday_is_the_same_day_on_a_later_call():
    friday = date_parts("Friday tak", SAT)["finish"]
    assert friday.same(date_parts("Friday tak", date(2026, 11, 28))["finish"])
    assert not friday.same(Day(date(2026, 12, 15)))


def test_meeting_words():
    assert meets("Theek hai, Monday ko milte hain.") and meets("सोमवार को मिलते हैं। बाय।") and meets("kal phone karna")
    assert meets("To Wednesday subah aa jao, 10 baje.") and meets("जी मैडम, सोमवार सुबह नौ बजे आ जाऊँगा।")
    assert not meets("Monday se kaam shuru")
