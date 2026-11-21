"""The contract stream's two OpenAI calls: write JSON with a reasoning model, and speak.
Each has a timeout and one retry. Tests replace this with fakes."""

import json

import httpx

from app.config import Settings

TEXT_MODEL = "gpt-6.2-sol"
SPEECH_MODEL = "gpt-4o-mini-tts"
VOICE = "marin"
SPEECH_STYLE = (
    "Speak in Hindi, clearly and warmly, at a calm and unhurried pace, like a trusted person "
    "reading the terms of a deal aloud to someone who cannot read. Say amounts in Hindi."
)
_BASE = "https://api.openai.com/v1"


class OpenAI:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def write(self, instructions: str, text: str, schema: dict) -> dict:
        """One answer from the reasoning model, as JSON that fits the schema."""
        response = await self._post("/responses", timeout=120, body={
            "model": TEXT_MODEL,
            "reasoning": {"effort": "low"},
            "instructions": instructions,
            "input": text,
            "text": {"format": {"type": "json_schema", "name": "contract", "strict": True, "schema": schema}},
        })
        parts = [
            part["text"]
            for item in response.json()["output"] if item["type"] == "message"
            for part in item["content"] if part["type"] == "output_text"
        ]
        return json.loads("".join(parts))

    async def speak(self, text: str) -> bytes:
        """The text as speech, in Ogg Opus: the format WhatsApp plays as a voice message."""
        response = await self._post("/audio/speech", timeout=60, body={
            "model": SPEECH_MODEL, "voice": VOICE, "input": text,
            "instructions": SPEECH_STYLE, "response_format": "opus",
        })
        return response.content

    async def _post(self, path: str, body: dict, timeout: float) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._settings.require('openai_api_key')}"}
        async with httpx.AsyncClient(base_url=_BASE, timeout=timeout, headers=headers) as client:
            for attempt in (1, 2):
                try:
                    response = await client.post(path, json=body)
                    if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                        if response.is_error:
                            # The body says what was wrong with the request; it never holds the key.
                            raise RuntimeError(f"OpenAI {path} {response.status_code}: {response.text[:300]}")
                        return response
                except httpx.TransportError:
                    if attempt == 2:
                        raise
        raise AssertionError("unreachable")
