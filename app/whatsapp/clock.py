"""The clock the send queue and the no-reply timer wait on. Tests swap in a fake one."""

import asyncio
import time


class Clock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
