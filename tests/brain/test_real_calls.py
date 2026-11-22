"""The moments on the user's own calls where they had to call Gawah by name, replayed through the
brain (tests/brain/real/: the lines, Gawah's turns and memory's facts as they came on the real call;
the brain's model lookups from tests/brain/real/recorded/). No outside calls.

Each test names the moment (deal, call.line) and checks Gawah now speaks there, for the right reason,
asked for the right kind of answer."""

from app.contracts import SpeakReason
from tests.brain.real.replay import Replay

_runs: dict[str, Replay] = {}


async def replay(deal: str) -> Replay:
    if deal not in _runs:
        _runs[deal] = await Replay(deal).run()
        assert not _runs[deal].missing(), "record the lookups again: uv run python -m tests.brain.real.replay record <deal>"
    return _runs[deal]


def one(run: Replay, call_no: int, line: int):
    [speak] = run.speak(call_no, line)
    return speak


async def test_24d9_after_the_advance_settles_gawah_names_what_is_left_before_anyone_asks():
    # L1.13 "गवाजी, कोई और बचा है?": Gawah had said nothing since the advance was agreed at L1.11.
    run = await replay("24d9c0bc0e72")
    named = one(run, 1, 11)
    assert named.reason is SpeakReason.OPEN_TERMS
    assert "still not agreed: the balance, the dates, what happens if the work is late or unfinished" in named.instruction
    asked = one(run, 1, 13)
    assert asked.reason is SpeakReason.ADDRESSED_DIRECTLY and "what is still left" in asked.instruction
    assert "Still not agreed: the balance, the dates" in asked.instruction


async def test_479b_the_balance_is_named_as_open_before_it_is_raised_and_dropped():
    # L1.10 "और बाकी का बैलेंस।" then L1.11 "गवां जी कुछ और बचा है?": the advance settled at L1.8, a
    # pause after L1.9, so Gawah names the open terms, the balance among them, before L1.10.
    run = await replay("479b7f788c68")
    named = one(run, 1, 9)
    assert named.reason is SpeakReason.OPEN_TERMS and "the balance" in named.instruction
    asked = one(run, 1, 11)
    # Answered with what is left, not the payments ("advance 5,000 agreed, payment abhi zero").
    assert asked.instruction.index("what is still left") < asked.instruction.index("money paid")
    assert "Still not agreed: the work, the total amount, the balance" in asked.instruction


async def test_479b_what_is_left_is_named_again_once_the_next_term_settles():
    # L1.17 "कुछ और बता बचा है गवांजी।"
    run = await replay("479b7f788c68")
    assert one(run, 1, 16).reason is SpeakReason.OPEN_TERMS
    assert "Still not agreed:" in one(run, 1, 17).instruction


async def test_479b_a_yes_to_the_offer_and_a_request_after_a_nahi_both_play_the_recording():
    # Call 2: L7 contradicts the record, Gawah offers the recording; L9 "हाँ सुनो।" is a yes to it, and
    # L10 "नहीं, पहले हमें वो रिकॉर्डिंग सुनाओ।" a request, whatever its first word.
    run = await replay("479b7f788c68")
    assert one(run, 2, 7).reason is SpeakReason.CONTRADICTS_RECORD
    for line in (9, 10):
        speak = one(run, 2, line)
        assert speak.reason is SpeakReason.ADDRESSED_DIRECTLY
        assert "They ask to hear a recording" in speak.instruction, line


async def test_6aae_terms_read_back_on_request_before_the_goodbye():
    # L1.28 "गवाजी, एक बार सारे टर्म्स वापस बोल दो।" then "बाय बाय": the read-back never came.
    run = await replay("6aae99c104d1")
    speak = one(run, 1, 28)
    assert speak.reason is SpeakReason.READ_BACK
    assert "Read back the agreed terms" in speak.instruction and "the total amount" in speak.instruction
    assert [s for s in run.speaks if s[0] == 1 and s[1].after_line > 28] == [], "read back once, not again at the goodbye"


async def test_6aae_questions_about_the_deal_to_no_one_are_answered_at_the_pause():
    # Call 2: L14 "अभी क्या-क्या बचा है डिस्कस करने के लिए?" and L16 "और मैं अब तक कितना पैसा ऑलरेडी दे
    # चुका हूँ?" went unanswered until the user added "गवाजी, बोलिए".
    run = await replay("6aae99c104d1")
    left = one(run, 2, 14)
    assert left.reason is SpeakReason.UNANSWERED_QUESTION and "They ask what is still left" in left.instruction
    paid = one(run, 2, 16)
    assert paid.reason is SpeakReason.UNANSWERED_QUESTION and "look it up with owed" in paid.instruction


async def test_6aae_a_wrong_recollection_is_answered_with_the_record():
    # Call 3: L3 "टोटल पच्चीस हज़ार तय हुआ था ना?" asked of the other person, then L6 "गवाजी सही अमाउंट
    # क्या था?". Gawah answers L3 at the pause with what the record holds for the amount.
    run = await replay("6aae99c104d1")
    speak = one(run, 3, 3)
    assert speak.reason is SpeakReason.UNANSWERED_QUESTION and speak.item.value == "amount"
    assert "say what the record holds for it, who said it and who agreed" in speak.instruction
    assert one(run, 3, 6).reason is SpeakReason.ADDRESSED_DIRECTLY


async def test_6aae_a_request_for_the_clip_after_gawahs_name_alone_is_answered():
    # Call 2: L11 "गवाजी।" alone, then L12 "क्या आप वो क्लिप दोहरा सकते हो?".
    run = await replay("6aae99c104d1")
    assert one(run, 2, 12).reason is SpeakReason.ADDRESSED_DIRECTLY
    assert run.speak(2, 11) == [], "a name alone asks nothing yet"
