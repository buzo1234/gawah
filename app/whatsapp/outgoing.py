"""One message Gawah sends, in the shape both providers take. Twilio sends the plain text
(any link is already in it) and the media; Meta also uses the buttons, the link button,
the file name, and reactions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Button:
    id: str  # comes back with the tap, so a tap can name what it answers
    title: str  # at most 20 characters on WhatsApp


@dataclass
class Outgoing:
    to: str
    text: str | None = None  # the whole message, links included
    media_url: str | None = None
    media_type: str | None = None
    filename: str | None = None  # a document's name on the phone
    buttons: tuple[Button, ...] = ()  # reply buttons under the text
    link: str | None = None  # a link inside the text that Meta shows as a button instead
    link_label: str | None = None
    react_to: str | None = None  # the provider id of a message to react to; the emoji is the text

    def logged_text(self) -> str | None:
        """What the event log and the dashboard show: the words, then the buttons as text."""
        if self.react_to:
            return f"{self.text} (reaction)"
        if self.buttons:
            return f"{self.text or ''}\n" + "  ".join(f"[{b.title}]" for b in self.buttons)
        return self.text

    def body_without_link(self) -> str:
        """The text for a message whose link goes in a button: 'Yeh link kholiye: <url>'
        becomes 'Yeh link kholiye.'"""
        text = self.text or ""
        if self.link:
            text = text.replace(f": {self.link}", ".").replace(self.link, "")
        return " ".join(text.split())
