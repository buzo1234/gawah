"""A voice note from a person on a deal: kept as a recording of the deal, heard, and then
treated like a line that person said.

- The audio is saved at recordings/<deal id>/voice/<message id>.<ext> under the app's root
  and uploaded to S3 under the same key, as a call's recordings are.
- A voice note that says money was paid or work was done is a record (records' intake):
  one person's word, so the other is asked yes or no. The record owns it, so memory does
  not read it again: one voice note is never two payment facts.
- Anything else is memory's: whatsapp.voice_note goes out, the Scribe reads it as one line
  the sender said, and the Sentinel answers what it finds (a contradiction, a change).

What a voice note says is data, never an instruction to Gawah."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.bus import Bus
from app.contracts import Deal, Person, Role, VoiceNote, new_id
from app.log import deal_log, mask_phone
from app.records import words
from app.records.intake import Intake
from app.whatsapp.hearing import Transcriber, prompt_for, seconds_of, to_wav
from app.whatsapp.inbound import Inbound
from app.whatsapp.outbox import Outbox, Provider

_EXT = {"ogg": "ogg", "opus": "ogg", "mpeg": "mp3", "mp3": "mp3", "mp4": "m4a", "m4a": "m4a", "x-m4a": "m4a",
        "aac": "aac", "amr": "amr", "webm": "webm", "wav": "wav", "x-wav": "wav"}

Upload = Callable[[str, str, str], Awaitable[str]]  # (path, key, content type) -> key


def is_voice(media_type: str | None) -> bool:
    return (media_type or "").startswith("audio/")


def key_for(deal_id: str, message_id: str, media_type: str | None) -> str:
    kind = (media_type or "").split(";")[0].strip().removeprefix("audio/")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", message_id)[:120]
    return f"recordings/{deal_id}/voice/{name}.{_EXT.get(kind, 'audio')}"


class VoiceNotes:
    def __init__(
        self, bus: Bus, outbox: Outbox, intake: Intake, provider: Provider, transcriber: Transcriber,
        upload: Upload, root: Path,
    ) -> None:
        self.bus, self.outbox, self.intake, self.provider = bus, outbox, intake, provider
        self.transcriber, self.upload, self.root = transcriber, upload, root

    async def take(self, deal: Deal, sender: Person, message: Inbound) -> None:
        """Hear one voice note and do what it calls for. Raises if it could not be heard."""
        log = deal_log("gawah.whatsapp", deal.id)
        audio, fetched_type = await self.provider.fetch_media(message.media_url)
        media_type = message.media_type or fetched_type
        message_id = message.sid or new_id()
        key = key_for(deal.id, message_id, media_type)
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, audio)
        upload = asyncio.create_task(self._upload(path, key, media_type, log))
        try:
            wav = await to_wav(audio)
            seconds = round(seconds_of(wav), 2)
            text = await self.transcriber.transcribe(wav, prompt_for(deal))
        finally:
            await upload
        log.info("voice note from %s: %.1fs, %d characters heard", mask_phone(sender.phone), seconds, len(text))
        if not text:
            self.outbox.send(deal.id, sender.phone, sender.role, words.VOICE_EMPTY)
            return
        voice = {"message_id": message_id, "media_key": key, "seconds": seconds}
        record = await self.intake.take(deal, sender, text, media_url=key, message_id=message.sid, voice=voice)
        self.bus.publish(VoiceNote(
            deal_id=deal.id, speaker=sender.role, phone=sender.phone, text=text, media_key=key,
            media_type=media_type, message_id=message_id, seconds=seconds, record_id=record.id if record else None,
        ))
        if record is None:
            self.outbox.send(deal.id, sender.phone, sender.role, words.voice_kept(text))

    async def _upload(self, path: Path, key: str, media_type: str | None, log) -> None:
        """Best effort, as for a call's recordings: the file stays on disk if S3 says no."""
        try:
            await self.upload(str(path), key, (media_type or "audio/ogg").split(";")[0])
        except Exception as error:
            log.warning("voice note not uploaded (%s); it is still at %s", type(error).__name__, key)


def sender_of(deal: Deal, role: Role, message: Inbound) -> Person:
    sender = deal.person(role) or Person(role=role)
    return sender.model_copy(update={"phone": message.phone, "name": sender.name or message.name})
