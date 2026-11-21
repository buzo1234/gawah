"""Reminders, once per deal and term. Each waiting reminder and each one already sent is
kept in a small JSON file beside the database, so a restart picks up the timers where they
were and never sends a reminder twice."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.contracts import ItemKey

if TYPE_CHECKING:
    from app.whatsapp.clock import Clock

log = logging.getLogger("gawah.records")

Key = tuple[str, str]  # deal id, item
# Called when a reminder is due: (deal id, item, why). True if it was sent.
Fire = Callable[[str, ItemKey, str], Awaitable[bool]]


class Reminders:
    def __init__(self, path: Path | None, clock: "Clock", wall: Callable[[], datetime], fire: Fire) -> None:
        self.path, self.clock, self.wall, self.fire = path, clock, wall, fire
        self.sent: set[Key] = set()
        self.due: dict[Key, tuple[datetime, str]] = {}
        self._tasks: dict[Key, asyncio.Task] = {}

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError) as error:
            log.error("deal=- could not read %s: %s", self.path.name, error)
            return
        self.sent = {tuple(k) for k in saved.get("sent", [])}
        for deal_id, item, when, why in saved.get("due", []):
            self.at(deal_id, ItemKey(item), datetime.fromisoformat(when), why)

    def at(self, deal_id: str, item: ItemKey, when: datetime, why: str) -> bool:
        """Remind about this term at `when`, unless it was already reminded or an earlier
        reminder for it is waiting. True if this one is now the one waiting."""
        key = (deal_id, item.value)
        if key in self.sent or (key in self.due and self.due[key][0] <= when):
            return False
        if key in self._tasks:
            self._tasks.pop(key).cancel()
        self.due[key] = (when, why)
        self._save()
        self._tasks[key] = asyncio.create_task(self._wait(key, when, why))
        return True

    async def _wait(self, key: Key, when: datetime, why: str) -> None:
        await self.clock.sleep(max(0.0, (when - self.wall()).total_seconds()))
        self._tasks.pop(key, None)
        try:
            sent = await self.fire(key[0], ItemKey(key[1]), why)
        except Exception:
            log.exception("deal=%s reminder for %s failed", *key)
            sent = False
        self.due.pop(key, None)
        if sent:
            self.sent.add(key)
        self._save()

    def _save(self) -> None:
        if not self.path:
            return
        due = [[d, i, when.isoformat(), why] for (d, i), (when, why) in self.due.items()]
        self.path.write_text(json.dumps({"sent": sorted(self.sent), "due": due}))

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
