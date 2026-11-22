"""A screenshot sent as proof of a disputed payment: kept beside the deal's recordings, on
disk and in S3, and a short-lived link to it for the other person."""

import asyncio
import mimetypes
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.log import deal_log
from app.whatsapp.voice import Upload

KeepProof = Callable[[str, str, bytes, str | None], Awaitable[str | None]]


def keeper(root: Path, upload: Upload, sign: Callable[[str], Awaitable[str]]) -> KeepProof:
    async def keep(deal_id: str, record_id: str, image: bytes, image_type: str | None) -> str | None:
        """The link to the kept screenshot; None when S3 cannot give one (the file stays on disk)."""
        media_type = (image_type or "image/png").split(";")[0]
        key = f"recordings/{deal_id}/proof/{record_id}{mimetypes.guess_extension(media_type) or '.png'}"
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, image)
        try:
            await upload(str(path), key, media_type)
            return await sign(key)
        except Exception as error:
            deal_log("gawah.whatsapp", deal_id).warning("proof screenshot not linked (%s); it is at %s", type(error).__name__, key)
            return None

    return keep
