"""How the Scribe reads Hindi and Hinglish, one cause at a time, on a scripted model. The
script answers each line as the model might, mistakes included, so the code that stands
behind the model is what is tested."""

from datetime import timedelta

from app.contracts import FactStatus, ItemKey, Role
from tests.memory.world import DAY1, DEAL, World, claim

H, W = Role.HIRER, Role.WORKER


def dates(stance, quote, value, kind="term", accepts_line=None):
    return claim("dates", stance, quote=quote, value=value, kind=kind, accepts_line=accepts_line)


async def test_hindi_number_words_are_read_whole(bus, tmp_path):
    """Cause 1: "adtees hazaar" is 38,000 whatever figure the model puts on it."""
    lines = [
        (W, "Tiles ka kaam adtees hazaar mein ho jayega."),
        (H, "Chhattees hazaar paanch sau mein karo."),
        (W, "Theek hai, chhattees hazaar paanch sau."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 20000, "adtees hazaar")],  # the model's misreading
        lines[1][1]: [claim("amount", "offer", 36000, "Chhattees hazaar paanch sau mein karo")],
        lines[2][1]: [claim("amount", "accept", 36500, "Theek hai, chhattees hazaar paanch sau", accepts_line=2)],
    })
    await world.call(lines)
    assert world.fact_from_line(1, 1).value_rupees == 38000
    term = await world.memory.get_term(DEAL, ItemKey.AMOUNT)
    assert (term.current.value_rupees, term.current.status, term.current.line_no) == (36500, FactStatus.AGREED, 2)
    assert world.conflicts == []


async def test_a_yes_with_a_danda_agrees_without_the_model(bus, tmp_path):
    """Cause 2: "ठीक है।" agrees to the offer just before it."""
    lines = [(W, "देर हुई तो हर दिन का चार सौ काट लेना।"), (H, "ठीक है।")]
    world = World(bus, tmp_path, {lines[0][1]: [claim("late_or_unfinished", "offer", 400, "हर दिन का चार सौ काट लेना")]})
    await world.call(lines)
    assert "ठीक है।" not in world.extractor.asked
    late = (await world.memory.get_term(DEAL, ItemKey.LATE_OR_UNFINISHED)).current
    assert (late.value_rupees, late.status, late.agreed_by) == (400, FactStatus.AGREED, [H])


async def test_a_list_of_figures_raises_no_contradiction(bus, tmp_path):
    """Cause 3: "बाईस हज़ार, पाँच एडवांस" is a total of 22,000 and an advance of 5,000."""
    summary = "तो टोटल बाईस हज़ार, पाँच एडवांस, बाकी काम के बाद।"
    lines = [
        (W, "बाईस हज़ार लगेगा, पाँच हज़ार एडवांस।"),
        (H, "ठीक है।"),
        (H, "एडवांस पाँच हज़ार पक्का?"),
        (W, "हाँ जी।"),
        (H, summary),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 22000, "बाईस हज़ार लगेगा")],
        lines[2][1]: [claim("advance", "offer", 5000, "एडवांस पाँच हज़ार पक्का")],
        summary: [claim("amount", "recall", 22000, summary), claim("advance", "recall", 5000, summary)],
    })
    await world.call(lines)
    assert (await world.memory.get_term(DEAL, ItemKey.AMOUNT)).current.value_rupees == 22000
    assert (await world.memory.get_term(DEAL, ItemKey.ADVANCE)).current.value_rupees == 5000
    assert world.conflicts == []


async def test_a_yes_that_opens_a_line_accepts_the_offer_before_it(bus, tmp_path):
    """Cause 4: "Chalo theek hai. To Wednesday..." accepts the 300 a day, even when the model
    gives no claim for the yes, or puts a stray acceptance on another term."""
    lines = [
        (W, "Late hua to roz ka 300 rupaye kaat lena madam."),
        (H, "Chalo theek hai. To Wednesday subah aa jao, aur baaki paisa kaam ke din dungi."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("late_or_unfinished", "offer", 300, "roz ka 300 rupaye kaat lena")],
        lines[1][1]: [claim("balance", "accept", quote="baaki paisa kaam ke din dungi", value="on the day of the work", accepts_line=1)],
    })
    await world.call(lines)
    late = (await world.memory.get_term(DEAL, ItemKey.LATE_OR_UNFINISHED)).current
    assert (late.value_rupees, late.agreed_by) == (300, [H])
    # Line 1 said nothing about the balance: the hirer's balance is her own proposal.
    balance = (await world.memory.get_term(DEAL, ItemKey.BALANCE)).history
    assert [(f.status, f.said_by) for f in balance] == [(FactStatus.SAID, H)]


async def test_a_counter_offer_after_the_yes_takes_it_back(bus, tmp_path):
    lines = [(W, "Late hua to roz ka 300 kaat lena."), (H, "Theek hai, par 300 nahi, 200 roz.")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("late_or_unfinished", "offer", 300, "roz ka 300 kaat lena")],
        lines[1][1]: [claim("late_or_unfinished", "offer", 200, "200 roz", value="200 rupees a day")],
    })
    await world.call(lines)
    assert (await world.memory.get_term(DEAL, ItemKey.LATE_OR_UNFINISHED)).current is None
    assert world.conflicts == []


AGREED_DATES = [
    (W, "Monday se shuru, 15 tarikh tak khatam."),
    (H, "Theek hai."),
]
AGREED_SCRIPT = {AGREED_DATES[0][1]: [dates("offer", AGREED_DATES[0][1], "start Monday, finish by the 15th")]}


async def test_a_meeting_day_is_not_the_agreed_date(bus, tmp_path):
    """Cause 5: "Monday ko milte hain" in a goodbye neither agrees nor changes the dates."""
    bye = "Theek hai, Monday ko milte hain. Bye."
    world = World(bus, tmp_path, AGREED_SCRIPT | {bye: [dates("accept", bye, "Monday", accepts_line=1)]})
    await world.call([*AGREED_DATES, (W, "Ji madam."), (H, bye)])
    term = await world.memory.get_term(DEAL, ItemKey.DATES)
    assert term.current.value == "start Monday, finish by the 15th" and term.current.line_no == 1
    assert [f.line_no for f in term.history] == [1, 1]
    assert world.conflicts == []


async def test_an_acceptance_of_nothing_the_other_said_is_an_offer(bus, tmp_path):
    lines = [(W, "Ji, isi number pe kar dena."), (H, "Chalo theek hai, kaam kal se start karo.")]
    world = World(bus, tmp_path, {lines[1][1]: [dates("accept", lines[1][1], "start tomorrow")]})
    await world.call(lines)
    [fact] = (await world.memory.get_term(DEAL, ItemKey.DATES)).history
    assert (fact.status, fact.said_by) == (FactStatus.SAID, H)


async def test_a_different_finish_contradicts_the_agreed_one(bus, tmp_path):
    """Cause 6: "bees tarikh" against a finish of the 15th that both agreed."""
    later = "Madam kaam bees tarikh tak ho jayega."
    same_start = "Monday se hi shuru karenge."
    world = World(bus, tmp_path, AGREED_SCRIPT | {
        later: [dates("state", later, "finish by the 20th")],
        same_start: [dates("state", same_start, "start Monday")],
    })
    await world.call([*AGREED_DATES, (W, same_start), (W, later)])
    agreed = world.fact_from_line(1, 1)
    [conflict] = world.conflicts
    assert conflict.fact_ids == [agreed.id] and conflict.line_no == 4
    assert conflict.explanation.startswith("Says a finish on Sunday 20 December; the finish was agreed as Tuesday 15 December by both")


async def test_a_different_start_on_a_later_call_contradicts_and_the_same_weekday_does_not(bus, tmp_path):
    moved = "Madam, Wednesday se shuru kar paunga."
    same = "Haan, Monday se shuru, pakka."
    world = World(bus, tmp_path, AGREED_SCRIPT | {
        same: [dates("recall", same, "start Monday")],
        moved: [dates("change", moved, "start Wednesday", kind="change")],
    })
    await world.call(AGREED_DATES)
    await world.call([(W, same), (W, moved)], call_no=2, at=DAY1 + timedelta(days=1))
    [conflict] = world.conflicts
    assert (conflict.call_no, conflict.line_no) == (2, 2)
    assert conflict.explanation.startswith("Says a start on Wednesday; the start was agreed as Monday")


async def test_saying_back_the_other_persons_figure_accepts_it(bus, tmp_path):
    """"पाँच हज़ार एडवांस मैं कल जीपे कर दूँगी" after the worker asked for 5,000 agrees to it,
    even when the model files it as a plain statement."""
    lines = [(W, "मटेरियल के लिए पाँच हज़ार पहले चाहिए।"), (H, "पाँच हज़ार एडवांस मैं कल जीपे कर दूँगी।")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("advance", "offer", 5000, "पाँच हज़ार पहले चाहिए")],
        lines[1][1]: [claim("advance", "state", 5000, lines[1][1])],
    })
    await world.call(lines)
    advance = (await world.memory.get_term(DEAL, ItemKey.ADVANCE)).current
    assert (advance.value_rupees, advance.said_by, advance.agreed_by, advance.line_no) == (5000, W, [H], 1)


async def test_sab_tay_ho_gaya_agrees_what_the_other_person_left_open(bus, tmp_path):
    lines = [
        (W, "Monday se shuru, Friday tak khatam."),
        (H, "Baaki paisa kaam ke din dungi."),
        (W, "Haan ji."),
        (H, "Chalo theek hai phir. Sab tay ho gaya."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [dates("state", lines[0][1], "start Monday, finish Friday")],
        lines[1][1]: [claim("balance", "state", quote=lines[1][1], value="on the day of the work")],
    })
    await world.call(lines)
    term = (await world.memory.get_term(DEAL, ItemKey.DATES)).current
    assert (term.status, term.said_by, term.agreed_by) == (FactStatus.AGREED, W, [H])
    assert (await world.memory.get_term(DEAL, ItemKey.BALANCE)).current.agreed_by == [W]  # her own term, his "haan ji"


async def test_a_question_with_no_figure_settles_nothing(bus, tmp_path):
    lines = [(W, "Ji. Aur baaki?"), (H, "Baaki kaam ke din, dekh ke."), (W, "Theek hai madam.")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("balance", "offer", quote="Aur baaki?", value="the rest")],
        lines[1][1]: [claim("balance", "accept", quote=lines[1][1], value="on the day of the work, after a look", accepts_line=1)],
    })
    await world.call(lines)
    balance = (await world.memory.get_term(DEAL, ItemKey.BALANCE)).current
    assert (balance.said_by, balance.agreed_by, balance.line_no) == (H, [W], 2)
