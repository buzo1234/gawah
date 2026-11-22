"""The Judge on what went wrong on calls it was not built on, one cause at a time, on
scripted answers (see test_judge_rules.py) and sentences written here.

5. Naming Gawah is not asking it something.
6. A question put to Gawah is answered at once, ahead of a question still waiting to be said.
7. With a dispute still standing, the goodbye gets a read-back that names it.
8. Wrapup mode answers questions too (test_judge_rules.py).
9. closing_soon through small talk is no wrap-up; leave-taking is.
"""

from app.brain.words import asks_gawah, takes_leave
from app.contracts import ItemKey, Role
from tests.brain.test_judge_rules import ITEMS, MOST, Call, Scripted

ASKED = {"addressed_gawah"}


def test_a_line_asks_gawah_only_with_a_question_or_a_request():
    assert asks_gawah("Gawah ji, balance kab dena tay hua tha?")
    assert asks_gawah("Achha Gawah, ek baar bata do total.")
    assert asks_gawah("गवाह जी एडवांस कितना बोला था")  # speech to text: no punctuation
    assert asks_gawah("Aapne sab likh liya na?")  # said to Gawah without its name
    assert not asks_gawah("Theek hai? Dekhiye, sab record ho raha hai, Gawah sun raha hai.")
    assert not asks_gawah("Gawah hai na saath mein, dar kis baat ka.")
    assert not asks_gawah("Likha hua achha hota hai, sabke liye.")


def test_leave_taking_is_a_goodbye_a_must_go_or_the_next_meeting():
    for line in ["Chalo bhai, kal milte hain.", "Mujhe office jaana hai abhi.", "Theek hai ji, phir baat karte hain.",
                 "To Friday subah aa jaana.", "धन्यवाद जी, नमस्ते", "Truck aa gaya, main baad mein karta hoon."]:
        assert takes_leave(line), line
    for line in ["Kal ka match dekha? Last over mein gaye.", "Aapka beta kya karta hai?", "Pakka, 25 tak ho jayega."]:
        assert not takes_leave(line), line


async def test_naming_gawah_in_passing_gets_no_answer(bus):
    call = Call(bus, Scripted(ASKED, ASKED), mouth=True)
    await call.say("Pakka? Dekho bhai, sab record ho raha hai, Gawah sun raha hai.")
    assert call.spoken == []
    await call.say("Gawah ji, aap batao, advance kitna tay hua tha?")
    assert call.spoken == [(2, "addressed_directly", None)]


async def test_a_question_to_gawah_does_not_wait_behind_a_held_question(bus):
    """No mouth: the balance question is out and unsaid. The question to Gawah a line later
    is answered at once, not after SPEAK_TIMEOUT_S."""
    call = Call(bus, Scripted({"advance_agreed", "balance_skipped"}, {"advance_agreed", *ASKED}))
    await call.say(takes=4.0)
    await call.say("Gawah, advance kitna likha aapne?", speaker=Role.WORKER, takes=4.0)
    assert call.spoken == [(1, "term_unclear", "balance"), (2, "addressed_directly", None)]
    assert call.speaks[1].to == "worker"


async def test_the_goodbye_reads_back_naming_what_is_still_in_dispute(bus):
    call = Call(bus, Scripted(
        set(ITEMS), set(), {"wrapping_up"}, {"wrapping_up"}, {"wrapping_up"},
    ), mouth=True)
    await call.say(takes=20.0)
    call.conflict(ItemKey.BALANCE, "Says 12,000 rupees; the balance was agreed at 9,000 rupees by both (call 1, line 1).")
    await call.say(takes=20.0)
    # The goodbye: the dispute is raised once more at wrap-up, and the read-back, naming it, goes in the same turn.
    await call.say("Theek hai, ab rakhta hoon.", takes=20.0)
    await call.say("Haan, namaste.", takes=20.0)
    assert call.spoken == [(1, "contradicts_record", "balance"), (3, "wrapping_up", "balance")]
    turn = call.speaks[1].instruction
    raised, read_back = turn.split(" Then, in the same turn, ")
    assert raised.startswith("They are about to hang up.") and "12,000" in raised
    assert read_back.startswith("Read back the agreed terms")
    assert "the total amount: the amount" in read_back and "the balance: the balance" not in read_back
    assert "Still in dispute" in read_back and "Says 12,000 rupees; the balance was agreed at 9,000" in read_back
    await call.say("Bye.", takes=20.0)
    assert len(call.speaks) == 2, "read back once"


async def test_closing_soon_through_small_talk_is_not_wrap_up(bus):
    small = {*MOST, "closing_soon"}
    call = Call(bus, Scripted(MOST, small, small, small, small, small))
    await call.say(takes=20.0)
    for line in ["Waise kal ka match dekha?", "Haan, aakhri over mein haar gaye.", "Mera bhatija stadium gaya tha."]:
        await call.say(line, takes=20.0)
    assert call.spoken == [], "the terms are done, but nobody is leaving"
    await call.say("Accha chalo, kal subah milte hain.", takes=20.0)
    assert call.spoken == [(5, "wrapping_up", "balance")]
