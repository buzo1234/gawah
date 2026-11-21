"""The SHA-256 of a recording, read through a signed link. Printed on the agreement so
the recording can later be shown to be unchanged. A timeout and one retry."""

import hashlib

import httpx


async def sha256_of(url: str) -> str:
    for attempt in (1, 2):
        try:
            digest = hashlib.sha256()
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        digest.update(chunk)
            return digest.hexdigest()
        except httpx.HTTPError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")
