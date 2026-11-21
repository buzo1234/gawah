"""Memory's two OpenAI calls: a small model's JSON reply, and embeddings. Each has a
timeout and one retry. Tests replace both with fakes. `calls` counts what was sent."""

import asyncio
import json
from collections import Counter

import httpx
import numpy as np

from app.config import Settings

BASE = "https://api.openai.com/v1"
EMBED_MODEL = "text-embedding-3-small"
_RETRY = (429, 500, 502, 503, 504)


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http: httpx.AsyncClient | None = None
        self.calls: Counter[str] = Counter()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            key = self._settings.require("openai_api_key")
            self._http = httpx.AsyncClient(base_url=BASE, headers={"Authorization": f"Bearer {key}"})
        return self._http

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def json_reply(self, model: str, system: str, user: str, schema: dict, effort: str, timeout: float) -> dict:
        body = {
            "model": model,
            "reasoning_effort": effort,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "reply", "strict": True, "schema": schema}},
        }
        response = await self._post("/chat/completions", body, timeout, f"chat:{model}")
        return json.loads(response.json()["choices"][0]["message"]["content"])

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        response = await self._post("/embeddings", {"model": EMBED_MODEL, "input": texts}, 15.0, "embed")
        rows = sorted(response.json()["data"], key=lambda r: r["index"])
        return [np.asarray(r["embedding"], dtype=np.float32) for r in rows]

    async def _post(self, path: str, body: dict, timeout: float, label: str) -> httpx.Response:
        for attempt in (1, 2):
            if attempt == 2:
                await asyncio.sleep(0.3)
            self.calls[label] += 1
            try:
                response = await self._client().post(path, json=body, timeout=timeout)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                continue
            if response.status_code in _RETRY and attempt == 1:
                continue
            if response.is_error:
                # The body says what was wrong with the request; it never holds the key.
                raise RuntimeError(f"OpenAI {path} {response.status_code}: {response.text[:300]}")
            return response
        raise AssertionError("unreachable")
