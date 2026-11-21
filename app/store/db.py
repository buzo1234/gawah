"""SQLite store. main.py subscribes record_event to every event: each one is appended
to the event log, and deals, people, transcript lines, and records are kept up to date
from it. Streams only read."""

import asyncio
import sqlite3
import threading
from datetime import UTC, datetime

from app.contracts import (
    NO_DEAL,
    AnyEvent,
    CallEnded,
    CallKind,
    CallStarted,
    ContractReady,
    Deal,
    DealRequested,
    DealStatus,
    Event,
    Person,
    Record,
    RecordConfirmed,
    RecordReceived,
    TranscriptLine,
    parse_event,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT, name TEXT, deal_id TEXT, ts TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS events_by_deal ON events (deal_id, name);
CREATE TABLE IF NOT EXISTS deals (id TEXT PRIMARY KEY, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS people (
    deal_id TEXT, role TEXT, name TEXT, phone TEXT, PRIMARY KEY (deal_id, role)
);
CREATE TABLE IF NOT EXISTS transcript_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, deal_id TEXT, payload TEXT);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    async def open(self) -> None:
        def _open() -> None:
            self._db = sqlite3.connect(self.path, check_same_thread=False)
            self._db.executescript(SCHEMA)

        await asyncio.to_thread(_open)

    async def close(self) -> None:
        if self._db:
            await asyncio.to_thread(self._db.close)
            self._db = None

    async def record_event(self, event: Event) -> None:
        await asyncio.to_thread(self._record, event)

    async def events(self, deal_id: str | None = None, name: str | None = None) -> list[AnyEvent]:
        """The event log, oldest first, optionally for one deal and one event name."""
        rows = await self._query(
            "SELECT payload FROM events WHERE (?1 IS NULL OR deal_id = ?1)"
            " AND (?2 IS NULL OR name = ?2) ORDER BY seq",
            (deal_id, name),
        )
        return [parse_event(payload) for (payload,) in rows]

    async def deal(self, deal_id: str) -> Deal | None:
        rows = await self._query("SELECT status, created_at FROM deals WHERE id = ?", (deal_id,))
        if not rows:
            return None
        people = await self._query(
            "SELECT role, name, phone FROM people WHERE deal_id = ? ORDER BY role", (deal_id,)
        )
        return Deal(
            id=deal_id,
            status=rows[0][0],
            created_at=rows[0][1],
            people=[Person(role=r, name=n, phone=p) for r, n, p in people],
        )

    async def transcript(self, deal_id: str) -> list[TranscriptLine]:
        rows = await self._query(
            "SELECT payload FROM transcript_lines WHERE deal_id = ? ORDER BY id", (deal_id,)
        )
        return [TranscriptLine.model_validate_json(payload) for (payload,) in rows]

    async def records(self, deal_id: str) -> list[Record]:
        rows = await self._query(
            "SELECT payload FROM records WHERE deal_id = ? ORDER BY rowid", (deal_id,)
        )
        return [Record.model_validate_json(payload) for (payload,) in rows]

    async def _query(self, sql: str, args: tuple) -> list[tuple]:
        def _run() -> list[tuple]:
            with self._lock:
                return self._db.execute(sql, args).fetchall()

        return await asyncio.to_thread(_run)

    def _record(self, event: Event) -> None:
        with self._lock, self._db as db:
            db.execute(
                "INSERT INTO events (event_id, name, deal_id, ts, payload) VALUES (?, ?, ?, ?, ?)",
                (event.event_id, event.name, event.deal_id, event.ts.isoformat(), event.model_dump_json()),
            )
            if event.deal_id == NO_DEAL:
                return
            db.execute(
                "INSERT OR IGNORE INTO deals (id, status, created_at) VALUES (?, ?, ?)",
                (event.deal_id, DealStatus.REQUESTED, datetime.now(UTC).isoformat()),
            )
            match event:
                case DealRequested():
                    self._people(db, event.deal_id, [event.requested_by, event.other])
                case CallStarted(kind=CallKind.DEAL):
                    self._people(db, event.deal_id, event.people)
                    self._status(db, event.deal_id, DealStatus.IN_CALL)
                case CallEnded(kind=CallKind.DEAL):
                    self._status(db, event.deal_id, DealStatus.CALL_ENDED)
                case ContractReady():
                    self._status(db, event.deal_id, DealStatus.CONTRACT_READY)
                case TranscriptLine():
                    db.execute(
                        "INSERT INTO transcript_lines (deal_id, payload) VALUES (?, ?)",
                        (event.deal_id, event.model_dump_json()),
                    )
                case RecordReceived():
                    db.execute(
                        "INSERT OR REPLACE INTO records (id, deal_id, payload) VALUES (?, ?, ?)",
                        (event.record.id, event.deal_id, event.record.model_dump_json()),
                    )
                case RecordConfirmed():
                    row = db.execute(
                        "SELECT payload FROM records WHERE id = ?", (event.record_id,)
                    ).fetchone()
                    if row:
                        record = Record.model_validate_json(row[0])
                        record.confirmed = event.confirmed
                        db.execute(
                            "UPDATE records SET payload = ? WHERE id = ?",
                            (record.model_dump_json(), record.id),
                        )

    @staticmethod
    def _status(db: sqlite3.Connection, deal_id: str, status: DealStatus) -> None:
        db.execute("UPDATE deals SET status = ? WHERE id = ?", (status, deal_id))

    @staticmethod
    def _people(db: sqlite3.Connection, deal_id: str, people: list[Person]) -> None:
        for p in people:
            # A later event with a blank name or phone must not wipe what we already know.
            db.execute(
                "INSERT INTO people (deal_id, role, name, phone) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (deal_id, role) DO UPDATE SET"
                " name = COALESCE(excluded.name, name), phone = COALESCE(excluded.phone, phone)",
                (deal_id, p.role, p.name, p.phone),
            )
