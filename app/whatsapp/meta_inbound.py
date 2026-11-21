"""Read Meta's webhook payload into the bot's Inbound messages. One payload can carry
several messages, and delivery reports (statuses) for messages Gawah sent."""

from collections.abc import Callable

from app.contracts import NO_DEAL
from app.log import deal_log, mask_phone
from app.whatsapp.bot import Inbound
from app.whatsapp.meta import HINTS

MEDIA = ("image", "document", "audio", "video")


def parse_meta(payload: dict, media_url: Callable[[str], str]) -> tuple[list[Inbound], list[dict], int]:
    """The messages, the delivery reports, and how many messages had no phone number (a
    person who shows only a username: the bot knows people by number, so they are skipped)."""
    messages, statuses, skipped = [], [], 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            statuses += value.get("statuses") or []
            for raw in value.get("messages") or []:
                digits = str(raw.get("from") or "")
                if not digits.isdigit():
                    skipped += 1
                    continue
                message = _read(raw, media_url)
                if message:
                    message.phone, message.name, message.sid = f"+{digits}", names.get(digits), raw.get("id")
                    messages.append(message)
    return messages, statuses, skipped


def _read(raw: dict, media_url: Callable[[str], str]) -> Inbound | None:
    kind = raw.get("type") or "unsupported"
    body = raw.get(kind) or {}
    if kind == "text":
        return Inbound(phone="", text=(body.get("body") or "").strip())
    if kind in MEDIA and body.get("id"):
        return Inbound(
            phone="", kind=kind, text=(body.get("caption") or "").strip(),
            media_url=media_url(body["id"]), media_type=body.get("mime_type"),
        )
    if kind == "interactive":  # a reply button or a list row, tapped
        tapped = body.get("button_reply") or body.get("list_reply") or {}
        return Inbound(phone="", kind="button", text=tapped.get("title", ""), button=tapped.get("id"))
    if kind == "button":  # a quick-reply button on a template
        return Inbound(phone="", kind="button", text=body.get("text", ""), button=body.get("payload"))
    if kind == "reaction":
        if not body.get("emoji"):
            return None  # a reaction taken back
        return Inbound(phone="", kind="reaction", text=f"{body['emoji']} (reaction)")
    if kind == "contacts":  # a shared contact card: the other person's number, and their name
        cards = raw.get("contacts") or []
        numbers = [f"+{p['wa_id']}" if p.get("wa_id") else p.get("phone", "") for c in cards for p in c.get("phones") or []]
        name = ((cards[0].get("name") or {}).get("formatted_name") if cards else None) or None
        return Inbound(phone="", kind="contacts", text=" ".join(filter(None, [name, *numbers])), other_name=name)
    # A sticker, a location, a poll, or anything WhatsApp calls unsupported: not a record.
    return Inbound(phone="", kind="other", text=f"({(body.get('type') if kind == 'unsupported' else None) or kind})")


def report_failures(statuses: list[dict], deal_of: dict[str, str]) -> None:
    """Log each message Meta accepted but could not deliver, with the reason. A message
    sent outside the 24-hour window, for one, is accepted first and fails only here."""
    for status in statuses:
        if status.get("status") != "failed":
            continue
        for error in status.get("errors") or [{}]:
            code = error.get("code")
            deal_log("gawah.whatsapp", deal_of.get(status.get("id", ""), NO_DEAL)).error(
                "not delivered to %s: code %s %s%s", mask_phone(status.get("recipient_id")), code,
                error.get("title", ""), f" ({HINTS[code]})" if code in HINTS else "",
            )
