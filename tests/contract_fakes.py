"""Stand-ins for the model, the speech, S3 and Chrome, and the terms of a practice call."""

from pathlib import Path

from app.contracts import ChecklistItem, ChecklistUpdated, ItemKey, ItemState

# The terms of fixtures/call_two_amounts.json once the amount is settled at 13,000.
TWO_AMOUNTS_TERMS = {
    ItemKey.WORK: ("Paint the 2BHK flat: walls 2 coats, ceiling 1 coat, enamel on the doors and the balcony railing, putty where needed", 5),
    ItemKey.AMOUNT: ("13,000 rupees, labour only; the hirer brings the paint", 12),
    ItemKey.ADVANCE: ("3,000 rupees in cash, tomorrow morning", 16),
    ItemKey.BALANCE: ("On the day the work is finished, after the hirer has checked the work", 18),
    ItemKey.DATES: ("Start on Wednesday, finish by next Monday evening", 23),
    ItemKey.LATE_OR_UNFINISHED: ("If late, 300 rupees cut per day. If left unfinished, no balance is paid and the advance is returned", 29),
}


def agreed_items(terms: dict = TWO_AMOUNTS_TERMS, pending: tuple[ItemKey, ...] = ()) -> list[ChecklistItem]:
    return [
        ChecklistItem(key=key) if key in pending
        else ChecklistItem(key=key, state=ItemState.AGREED, value=value, confidence=0.9, line_no=line_no)
        for key, (value, line_no) in terms.items()
    ]


def checklist(deal_id: str, **kwargs) -> ChecklistUpdated:
    return ChecklistUpdated(deal_id=deal_id, items=agreed_items(**kwargs))


def answer_for(items: list[ChecklistItem], **changes) -> dict:
    """What a well-behaved model returns: each value restated in both languages."""
    answer = {
        "hirer_name": {"hi": "सुनीता", "en": "Sunita"},
        "worker_name": {"hi": "रमेश", "en": "Ramesh"},
        "terms": {
            i.key.value: {"hi": f"तय हुआ: {i.value}", "en": i.value}
            for i in items if i.state is ItemState.AGREED
        },
        "summary_hi": " ".join(["सौदा"] * 50),
    }
    return answer | changes


class FakeWriter:
    """Answers from a list, one per call; after the list runs out, a good answer."""

    def __init__(self, items: list[ChecklistItem] | None = None, answers: list[dict] | None = None) -> None:
        self.items, self.answers, self.calls = items, list(answers or []), []

    async def write(self, instructions: str, text: str, schema: dict) -> dict:
        self.calls.append(text)
        if self.answers:
            return self.answers.pop(0)
        return answer_for(self.items or agreed_items())


class FakeSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str) -> bytes:
        self.spoken.append(text)
        return b"OggS" + bytes(2) + (48000 * 25).to_bytes(8, "little")


class FakeFiles:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.uploaded = fail, {}

    async def upload(self, path: str, key: str, content_type: str | None = None) -> str:
        if self.fail:
            raise RuntimeError("ExpiredToken: the security token included in the request is expired")
        self.uploaded[key] = (Path(path).read_bytes(), content_type)
        return key

    async def signed_url(self, key: str, expires_seconds: int = 900) -> str:
        return f"https://signed.invalid/{key}"


async def fake_render_pdf(html: str, out: Path) -> None:
    out.write_bytes(b"%PDF-fake " + html.encode())
