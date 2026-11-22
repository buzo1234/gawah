"""Readings that went wrong on calls the Scribe was not built on, one cause at a time, each
on sentences written here, in trades and wordings of their own. The script answers each
line as the model might, mistakes included, so what is tested is the code behind the model.

1. Saying the other person's figure back accepts it only with a yes or a promise.
2. An extra agreed on top of a total, a balance paid in parts, a rate.
4. An offer while a change is bargained is a change, not a contradiction.
"""

from datetime import timedelta

from app.contracts import FactKind, FactStatus, ItemKey, Role
from tests.memory.world import AGREED_CHANGE, DAY1, DEAL, World, claim

H, W = Role.HIRER, Role.WORKER


async def amount(world: World):
    return (await world.memory.get_term(DEAL, ItemKey.AMOUNT)).current


# ---- 1. an echo is not an acceptance ----

async def test_a_complaint_about_their_figure_accepts_nothing(bus, tmp_path):
    lines = [
        (W, "Teen darwaze wali almari, plywood ke saath, 18,000 lagega."),
        (H, "18,000 to kaafi zyada hai bhai, market mein 14 mein ho jaati hai."),
        (W, "Chaliye 16 kar dete hain, isse neeche nahi."),
        (H, "16 theek hai, kal se lag jao."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 18000, "18,000 lagega")],
        # The model hears the hirer's own figure said back as a plain statement of it.
        lines[1][1]: [claim("amount", "state", 18000, "18,000 to kaafi zyada hai bhai")],
        lines[2][1]: [claim("amount", "offer", 16000, "Chaliye 16 kar dete hain")],
        lines[3][1]: [claim("amount", "state", 16000, "16 theek hai")],
    })
    await world.call(lines)
    agreed = await amount(world)
    assert (agreed.value_rupees, agreed.said_by, agreed.agreed_by) == (16000, W, [H])
    assert world.conflicts == []
    assert all(f.value_rupees != 18000 or f.status == FactStatus.SAID for f in world.versions)


async def test_a_hedge_a_question_or_a_deferral_accepts_nothing(bus, tmp_path):
    cases = [
        ("Baarah mein to patli chaddar ka gate banega, madam.", "accept"),  # a hedge before a counter
        ("Baarah? Paint aur fitting milake?", "accept"),  # a question
        ("Baarah wala baad mein dekhenge, pehle naap le lo.", "state"),  # a deferral
    ]
    for n, (reply, stance) in enumerate(cases):
        world = World(bus, tmp_path / str(n), {
            "Lohe ka gate, paint ke saath, baarah hazaar.": [claim("amount", "offer", 12000, "baarah hazaar")],
            reply: [claim("amount", stance, 12000, reply, accepts_line=1)],
        })
        await world.call([(W, "Lohe ka gate, paint ke saath, baarah hazaar."), (H, reply)])
        assert await amount(world) is None, reply


async def test_their_figure_said_back_with_a_promise_or_after_a_pause_accepts_it(bus, tmp_path):
    for n, reply in enumerate(["Theek hai, sattar sau parson de dungi.", "Sattar sau... theek hai, kar do."]):
        world = World(bus, tmp_path / str(n), {
            "Poore ghar ki wiring check, sattar sau.": [claim("amount", "offer", 7000, "sattar sau")],
            reply: [claim("amount", "state", 7000, reply)],  # filed as a statement, not an acceptance
        })
        await world.call([(W, "Poore ghar ki wiring check, sattar sau."), (H, reply)])
        agreed = await amount(world)
        assert (agreed.value_rupees, agreed.status, agreed.agreed_by) == (7000, FactStatus.AGREED, [H]), reply


async def test_a_bare_figure_said_back_takes_the_scale_it_was_said_with(bus, tmp_path):
    lines = [(W, "Teesri manzil ka lenter, dhai lakh mein."), (H, "Dhai. Theek hai.")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 250000, "dhai lakh")],
        lines[1][1]: [claim("amount", "accept", 2500, "Dhai. Theek hai.", accepts_line=1)],  # scaled wrong
    })
    await world.call(lines)
    assert (await amount(world)).value_rupees == 250000
    assert world.conflicts == []


# ---- 2. totals, add-ons, instalments, rates ----

TILES = [
    (W, "Kitchen aur bathroom ki tiles, material aapka, 40,000."),
    (H, "Theek hai, 40,000."),
    (W, "Pandrah hazaar pehle, phir 20 jab deewar ho jaye, aur 5 kaam khatam hone par."),
    (H, "Haan, chalega."),
]
TILES_SCRIPT = {
    TILES[0][1]: [claim("amount", "offer", 40000, "40,000")],
    TILES[1][1]: [claim("amount", "accept", 40000, "Theek hai, 40,000", accepts_line=1)],
    TILES[2][1]: [
        claim("advance", "offer", 15000, "Pandrah hazaar pehle"),
        claim("balance", "offer", 25000, TILES[2][1], value="20,000 when the walls are done; 5,000 at the end"),
    ],
}


async def test_a_balance_in_parts_is_one_schedule_and_its_parts_do_not_clash(bus, tmp_path):
    world = World(bus, tmp_path, TILES_SCRIPT | {
        TILES[3][1]: [
            claim("advance", "accept", 15000, "Haan, chalega", accepts_line=3),
            claim("balance", "accept", 25000, "Haan, chalega", accepts_line=3, value="20,000 when the walls are done; 5,000 at the end"),
        ],
        "Deewar ho gayi to 20 ready rakhna.": [claim("balance", "state", 20000, "20 ready rakhna", figure="part")],
        "Aakhir mein 15 dena hai na?": [claim("balance", "recall", 15000, "Aakhir mein 15 dena hai", figure="part")],
    })
    await world.call(TILES)
    balance = (await world.memory.get_term(DEAL, ItemKey.BALANCE)).current
    assert (balance.value_rupees, balance.status) == (25000, FactStatus.AGREED)
    assert world.conflicts == []
    await world.call([(W, "Deewar ho gayi to 20 ready rakhna."), (W, "Aakhir mein 15 dena hai na?")], call_no=2, at=DAY1 + timedelta(days=3))
    [conflict] = world.conflicts
    assert conflict.line_no == 2, "20,000 is one of the payments; 15,000 is none of them"


async def test_an_extra_bargained_and_agreed_is_added_to_the_total(bus, tmp_path):
    """The extra is bargained (6, 4, 5) and agreed at 5: the total becomes 45,000, not 5,000,
    no offer is a contradiction, and the payment it was put into takes it."""
    later = [
        (W, "Balcony ka farsh bhi karna hai to 6,000 extra lagenge."),
        (H, "Chaar de dungi."),
        (W, "Paanch kar lo madam, kam nahi hoga."),
        (H, "Paanch theek hai, kar do. Aakhri wale ke saath de dungi."),
        (W, "Ji, to aakhir mein 10, pakka."),
        (H, "Eent ka rate 9 rupaye ho gaya sunne mein aaya."),
    ]
    world = World(bus, tmp_path, TILES_SCRIPT | {
        TILES[3][1]: [
            claim("advance", "accept", 15000, "Haan, chalega", accepts_line=3),
            claim("balance", "accept", 25000, "Haan, chalega", accepts_line=3, value="20,000 when the walls are done; 5,000 at the end"),
        ],
        later[0][1]: [claim("amount", "offer", 6000, "6,000 extra lagenge", kind="change", figure="addition")],
        later[1][1]: [claim("amount", "offer", 4000, "Chaar de dungi", kind="change", figure="addition")],
        later[2][1]: [claim("amount", "offer", 5000, "Paanch kar lo madam", kind="term")],  # the model forgets it is an extra
        later[3][1]: [claim("amount", "accept", 5000, "Paanch theek hai, kar do", kind="change", figure="addition", accepts_line=3)],
        later[4][1]: [claim("balance", "accept", 10000, "aakhir mein 10, pakka", figure="part")],
        later[5][1]: [claim("amount", "state", 9, "Eent ka rate 9 rupaye", figure="rate")],
    })
    await world.call(TILES)
    first = await amount(world)
    await world.call(later, call_no=2, at=DAY1 + timedelta(days=2))
    assert world.conflicts == []
    # Both said it, and it is still only an agreed change: the term holds until both confirm it through Gawah.
    assert (await amount(world)).id == first.id
    [raised] = world.open_changes(ItemKey.AMOUNT)
    assert ((raised.kind, raised.status), raised.value_rupees, raised.agreed_by) == (AGREED_CHANGE, 45000, [H])
    [carried] = world.open_changes(ItemKey.BALANCE)
    assert (carried.kind, carried.status) == AGREED_CHANGE and carried.value_rupees == 30000 and "10,000 at the end" in carried.value
    await world.confirm_through_gawah(raised, W)
    await world.confirm_through_gawah(carried, W)
    total = await amount(world)
    assert (total.value_rupees, total.status, total.replaces) == (45000, FactStatus.CONFIRMED, first.id)
    assert world.memory.book.fact(first.id).status == FactStatus.SUPERSEDED
    assert world.open_changes(ItemKey.AMOUNT) == [] and world.open_changes(ItemKey.BALANCE) == []
    balance = (await world.memory.get_term(DEAL, ItemKey.BALANCE)).current
    assert balance.value_rupees == 30000 and "10,000 at the end" in balance.value
    owed = {r.item: r.agreed_rupees for r in await world.memory.owed(DEAL)}
    assert owed[ItemKey.AMOUNT] == 45000 and owed[ItemKey.BALANCE] == 30000


async def test_a_rate_is_not_the_total(bus, tmp_path):
    lines = [(W, "Poori deewar 1,20,000 mein, material samet."), (H, "Theek hai."), (W, "Eent abhi 9 rupaye ki chal rahi hai.")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 120000, "1,20,000 mein")],
        lines[2][1]: [claim("amount", "state", 9, "9 rupaye ki", figure="rate", kind="change")],
    })
    await world.call(lines)
    assert (await amount(world)).value_rupees == 120000
    assert world.conflicts == []
    assert not [f for f in world.versions if f.kind == FactKind.CHANGE and f.value_rupees]


# ---- 4. an offer while a change is bargained ----

async def test_a_new_figure_offered_for_an_agreed_term_is_a_change_not_a_contradiction(bus, tmp_path):
    lines = [
        (W, "Do kamre ki safai, 3,000."),
        (H, "Theek hai, 3,000."),
        (W, "Madam, sofa bhi hai to 3,500 kar dete hain."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 3000, "3,000")],
        lines[1][1]: [claim("amount", "accept", 3000, "Theek hai, 3,000", accepts_line=1)],
        lines[2][1]: [claim("amount", "offer", 3500, "3,500 kar dete hain")],
    })
    await world.call(lines)
    assert world.conflicts == []
    offered = world.fact_from_line(1, 3)
    assert (offered.kind, offered.status, offered.value_rupees) == (FactKind.CHANGE, FactStatus.SAID, 3500)
    assert (await amount(world)).value_rupees == 3000, "an offer changes nothing until it is accepted"


async def test_a_bare_yes_to_a_new_total_does_not_change_it(bus, tmp_path):
    lines = [
        (W, "Do kamre ki safai, 3,000."),
        (H, "Theek hai, 3,000."),
        (W, "To total 3,500 hua na madam."),
        (H, "Haan theek hai. Kal subah aa jaana."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 3000, "3,000")],
        lines[1][1]: [claim("amount", "accept", 3000, "Theek hai, 3,000", accepts_line=1)],
        lines[2][1]: [claim("amount", "offer", 3500, "total 3,500 hua na", kind="change")],
        lines[3][1]: [claim("amount", "accept", 3500, "Haan theek hai", accepts_line=3, kind="change")],
    })
    await world.call(lines)
    assert (await amount(world)).value_rupees == 3000, "a change is agreed only with its figure said back"


async def test_an_extra_asked_for_and_given_as_a_plain_figure_is_still_an_extra(bus, tmp_path):
    """The model files "aath hazaar" after "kitna extra lagega?" as a whole figure: far below
    the agreed total, it is the extra. Accepted twice, it is added once."""
    lines = [
        (W, "Poore ghar ki plumbing, 60,000 mein."),
        (H, "Theek hai, 60,000."),
        (H, "Chhat ki tanki bhi badalni hai. Kitna extra lagega?"),
        (W, "Tanki aur fitting milake aath hazaar."),
        (H, "Saat kar do."),
        (W, "Saadhe saat, isse kam nahi."),
        (H, "Saadhe saat theek hai, laga do."),
        (W, "Ji, saadhe saat pakka."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 60000, "60,000 mein")],
        lines[1][1]: [claim("amount", "accept", 60000, "Theek hai, 60,000", accepts_line=1)],
        lines[3][1]: [claim("amount", "offer", 8000, "aath hazaar")],
        lines[4][1]: [claim("amount", "offer", 7000, "Saat kar do", kind="change")],
        lines[5][1]: [claim("amount", "offer", 7500, "Saadhe saat")],
        lines[6][1]: [claim("amount", "accept", 7500, "Saadhe saat theek hai", kind="change", accepts_line=6)],
        lines[7][1]: [claim("amount", "accept", 7500, "saadhe saat pakka", kind="change", accepts_line=7)],
    })
    await world.call(lines)
    assert (await amount(world)).value_rupees == 60000, "agreed on the call, it waits for both to confirm it through Gawah"
    [extra] = world.open_changes(ItemKey.AMOUNT)
    assert (extra.kind, extra.status, extra.value_rupees) == (*AGREED_CHANGE, 67500)
    assert world.conflicts == []


async def test_asking_what_a_figure_was_contradicts_nothing_saying_it_does(bus, tmp_path):
    lines = [(W, "Painting 30,000."), (H, "Theek hai, 30,000."), (H, "Kitna bola tha aapne, 32?"), (W, "Total 32 tay hua tha na?")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 30000, "Painting 30,000")],
        lines[1][1]: [claim("amount", "accept", 30000, "Theek hai, 30,000", accepts_line=1)],
        lines[2][1]: [claim("amount", "recall", 32000, "Kitna bola tha aapne, 32?", kind="change")],
        lines[3][1]: [claim("amount", "recall", 32000, "Total 32 tay hua tha na?", kind="change")],
    })
    await world.call(lines)
    assert [c.line_no for c in world.conflicts] == [4]


# ---- a promise to pay is not a payment ----

async def test_a_promise_to_pay_is_a_term_even_when_the_model_calls_it_a_payment(bus, tmp_path):
    """The model files each of these as money paid; worded as a promise, it is the term. Only
    the last, said as done, is a payment, so 6,000 of the 20,000 is owed off, not 20,000."""
    lines = [
        (W, "Rasoi ki chimney fitting, 20,000 lagenge."),
        (H, "Theek hai, 20,000."),
        (H, "छह हज़ार एडवांस मैं परसों भेज दूंगी।"),
        (H, "Baaki 14 kaam ke baad de dungi."),
        (H, "Chalo, 6,000 abhi GPay kar diya."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 20000, "20,000 lagenge")],
        lines[1][1]: [claim("amount", "accept", 20000, "Theek hai, 20,000", accepts_line=1)],
        lines[2][1]: [claim("advance", "state", 6000, lines[2][1], kind="payment")],
        lines[3][1]: [claim(None, "state", 14000, "Baaki 14 kaam ke baad de dungi", kind="payment")],
        lines[4][1]: [claim("advance", "state", 6000, "6,000 abhi GPay kar diya", kind="payment")],
    })
    await world.call(lines)
    payments = [f for f in world.versions if f.kind == FactKind.PAYMENT]
    assert [p.line_no for p in payments] == [5]
    assert world.fact_from_line(1, 3).item == ItemKey.ADVANCE and world.fact_from_line(1, 4).item == ItemKey.BALANCE
    owed = {r.item: r.owed_rupees for r in await world.memory.owed(DEAL)}
    assert owed[ItemKey.AMOUNT] == 14000
