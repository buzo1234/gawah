"""What a person sent on WhatsApp, in one shape whichever provider brought it, and the
readers that do not need the bot: Twilio's form, and a request to delete one's data.
Meta's payload is read in meta_inbound.py."""

import re
from dataclasses import dataclass

# "delete my data", "mera data delete karo", "data hata do": the privacy policy promises
# that this request is heard. The removal itself is done by hand (tools/DELETE-DATA.md).
_DELETE = re.compile(
    r"\b(delete|remove|erase)\s+(all\s+)?(of\s+)?my\s+(deal\s+)?data\b"
    r"|\bdata\s+(delete|del|hata|hatao|hataa|hatado|mita|mitao|remove|nikal|nikalo)\b"
    r"|डेटा\s+(डिलीट|हटा|मिटा)",
    re.IGNORECASE,
)


def asks_to_delete(text: str) -> bool:
    return bool(_DELETE.search(text))


@dataclass
class Inbound:
    phone: str
    text: str = ""
    media_url: str | None = None
    media_type: str | None = None
    name: str | None = None  # the person's WhatsApp profile name
    sid: str | None = None  # the provider's message id
    kind: str = "text"  # text, image, document, audio, video, button, reaction, contacts, other
    button: str | None = None  # the id of a tapped reply button; its title is the text
    other_name: str | None = None  # the name on a shared contact card


def parse_inbound(form: dict[str, str]) -> Inbound | None:
    """The fields Twilio posts for an inbound WhatsApp message. None if there is no sender."""
    # An unescaped + in a form body decodes to a space, so put it back.
    digits = form.get("From", "").removeprefix("whatsapp:").strip().lstrip("+")
    if not digits.isdigit():
        return None
    has_media = (form.get("NumMedia") or "0") != "0" and form.get("MediaUrl0")
    return Inbound(
        phone=f"+{digits}",
        text=form.get("Body", "").strip(),
        media_url=form["MediaUrl0"] if has_media else None,
        media_type=form.get("MediaContentType0") if has_media else None,
        name=form.get("ProfileName") or None,
        sid=form.get("MessageSid") or None,
    )
