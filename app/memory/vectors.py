"""Embeddings for facts and lines, cached on disk so a restart does not re-embed, and
fetched in batches off the critical path."""

import asyncio
import base64
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger("gawah.memory")

FLUSH_AFTER_S = 0.5
BATCH = 128


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class WordHashEmbedder:
    """Used when there is no OpenAI key, and in tests: each word hashed into a fixed number
    of slots. It finds shared words, not meaning."""

    def __init__(self, dims: int = 512) -> None:
        self.dims = dims
        self.calls = 0

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls += 1
        out = []
        for text in texts:
            v = np.zeros(self.dims, dtype=np.float32)
            for word in re.findall(r"\w+", text.lower()):
                if len(word) > 2:
                    v[int(hashlib.md5(word.encode()).hexdigest()[:8], 16) % self.dims] += 1
            out.append(v)
        return out


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


class Vectors:
    def __init__(self, embedder: Embedder, cache_dir: Path | None, model: str = "text-embedding-3-small") -> None:
        self.embedder = embedder
        self.cache: dict[str, np.ndarray] = {}
        self._wanted: dict[str, str] = {}
        self._flusher: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._file = cache_dir / f"embeddings-{model}.jsonl" if cache_dir else None
        if self._file and self._file.exists():
            for row in self._file.read_text().splitlines():
                try:
                    entry = json.loads(row)
                    self.cache[entry["k"]] = np.frombuffer(base64.b64decode(entry["v"]), dtype=np.float32)
                except (ValueError, KeyError):
                    continue

    def want(self, text: str) -> None:
        """Embed this text soon, in a batch with others."""
        key = _key(text)
        if key not in self.cache:
            self._wanted[key] = text
            if self._flusher is None or self._flusher.done():
                self._flusher = asyncio.create_task(self._flush_later())

    async def matrix(self, texts: list[str]) -> np.ndarray:
        """Unit vectors for the texts, one row each; anything missing is embedded now."""
        missing = {_key(t): t for t in texts if _key(t) not in self.cache}
        if missing:
            await self._embed(missing)
        rows = [self.cache[_key(t)] for t in texts]
        m = np.vstack(rows) if rows else np.zeros((0, 1), dtype=np.float32)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)

    async def close(self) -> None:
        if self._flusher:
            self._flusher.cancel()

    async def _flush_later(self) -> None:
        while self._wanted:
            await asyncio.sleep(FLUSH_AFTER_S)
            wanted, self._wanted = self._wanted, {}
            try:
                await self._embed(wanted)
            except Exception:
                log.exception("deal=- embedding %d texts failed; they are embedded when searched", len(wanted))

    async def _embed(self, texts: dict[str, str]) -> None:
        async with self._lock:
            todo = [(k, t) for k, t in texts.items() if k not in self.cache]
            for start in range(0, len(todo), BATCH):
                chunk = todo[start:start + BATCH]
                vectors = await self.embedder.embed([t for _, t in chunk])
                rows = []
                for (key, _), vec in zip(chunk, vectors, strict=True):
                    self.cache[key] = vec.astype(np.float32)
                    rows.append(json.dumps({"k": key, "v": base64.b64encode(self.cache[key].tobytes()).decode()}))
                if self._file:
                    self._file.parent.mkdir(parents=True, exist_ok=True)
                    with self._file.open("a") as f:
                        f.write("\n".join(rows) + "\n")
