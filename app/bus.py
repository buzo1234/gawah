"""In-process event bus. Frozen after the scaffold.

Each subscription has its own queue and its own worker task, so:
- publish() never waits for a handler,
- a slow or failing handler only affects itself,
- one handler sees events one at a time, in the order they were published.

A handler that needs to do long work without holding up its own later events
should start a task for it.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.contracts import EVENTS, AnyEvent, Event

log = logging.getLogger("gawah.bus")

Handler = Callable[[AnyEvent], Awaitable[None]]


class _Subscription:
    def __init__(self, name: str | None, handler: Handler) -> None:
        self.name = name
        self.handler = handler
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None


class Bus:
    def __init__(self) -> None:
        self._subs: list[_Subscription] = []
        self._started = False
        self._pending = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def subscribe(self, event_type: type[Event] | str, handler: Handler) -> Callable[[], None]:
        """Call handler for every event of one type. Pass the event class or its name.
        Returns a function that removes the subscription."""
        name = event_type if isinstance(event_type, str) else event_type.model_fields["name"].default
        if name not in EVENTS:
            raise ValueError(f"no such event: {name!r}")
        return self._add(_Subscription(name, handler))

    def subscribe_all(self, handler: Handler) -> Callable[[], None]:
        """Call handler for every event."""
        return self._add(_Subscription(None, handler))

    def publish(self, event: Event) -> None:
        """Hand the event to every matching handler and return at once. Not a coroutine:
        do not await it. Call it from the event loop's thread; from another thread use
        loop.call_soon_threadsafe(bus.publish, event)."""
        for sub in self._subs:
            if sub.name is None or sub.name == event.name:
                self._pending += 1
                self._idle.clear()
                sub.queue.put_nowait(event)

    def start(self) -> None:
        """Start delivering. main.py calls this on startup. Events published before
        start are kept and delivered once it runs."""
        self._started = True
        for sub in self._subs:
            self._spawn(sub)

    async def stop(self) -> None:
        self._started = False
        tasks = [sub.task for sub in self._subs if sub.task]
        for sub in self._subs:
            sub.task = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait until every published event has been handled, including events that
        handlers published in turn. For tests."""
        await asyncio.wait_for(self._idle.wait(), timeout)

    def _add(self, sub: _Subscription) -> Callable[[], None]:
        self._subs.append(sub)
        if self._started:
            self._spawn(sub)

        def unsubscribe() -> None:
            if sub in self._subs:
                self._subs.remove(sub)
                self._done(sub.queue.qsize())
                if sub.task:
                    sub.task.cancel()

        return unsubscribe

    def _spawn(self, sub: _Subscription) -> None:
        if sub.task is None:
            sub.task = asyncio.create_task(self._run(sub))

    def _done(self, count: int = 1) -> None:
        self._pending -= count
        if self._pending <= 0:
            self._pending = 0
            self._idle.set()

    async def _run(self, sub: _Subscription) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
            except Exception:
                log.exception(
                    "deal=%s handler %s failed on %s",
                    event.deal_id,
                    getattr(sub.handler, "__qualname__", sub.handler),
                    event.name,
                )
            finally:
                self._done()
