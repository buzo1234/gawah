"""Whether a deal call is ending, from Sage2's answers, the checklist, and the silence
after a line. See tuning.py for why each signal is there."""

import asyncio
from collections.abc import Callable, Hashable

from app.brain import tuning
from app.brain.sage import Answers, yes
from app.brain.words import takes_leave


class Closing:
    def __init__(self) -> None:
        self.soon_before = False  # closing_soon on the line before
        self.leave_before = False  # the line before takes leave
        self.settled_on: set[int] = set()  # lines on which an item was first agreed
        self._timer: asyncio.Task | None = None
        self._waiting_on: Hashable | None = None

    def on_line(self, answers: Answers, line_no: int, agreed: int, text: str = "") -> bool:
        """True if this line says they are wrapping up. closing_soon twice also says yes through
        small talk once the terms are done (cricket, family), so one of the two lines must take
        leave: a goodbye, thanks, "milte hain", "mujhe jaana hai"."""
        soon, leave = yes(answers, "closing_soon"), takes_leave(text)
        quiet_pair = soon and self.soon_before and not {line_no, line_no - 1} & self.settled_on
        leaving = leave or self.leave_before
        self.soon_before, self.leave_before = soon, leave
        return yes(answers, "wrapping_up") or (quiet_pair and leaving and agreed >= tuning.CLOSE_MIN_AGREED)

    @staticmethod
    def silence_would_close(answers: Answers, discussed: int) -> bool:
        """True if CLOSING_SILENCE_S with no new line after this one would mean they are done."""
        return yes(answers, "closing_soon") and discussed >= tuning.CLOSE_MIN_DISCUSSED

    def wait(self, state: Hashable | None, on_silence: Callable[[], None]) -> None:
        """Start timing a silence from now, or with state None just stop. `state` says what
        has happened so far (lines, things Gawah said); silence_passed checks it is unchanged."""
        if self._timer:
            self._timer.cancel()
        self._timer, self._waiting_on = None, state
        if state is not None:
            self._timer = asyncio.create_task(self._sleep(on_silence))

    async def _sleep(self, on_silence: Callable[[], None]) -> None:
        await asyncio.sleep(tuning.CLOSING_SILENCE_S)
        on_silence()

    def silence_passed(self, state: Hashable) -> bool:
        """True once per wait, if nothing has happened since it began."""
        waited, self._waiting_on = self._waiting_on, None
        return waited is not None and waited == state

    @property
    def waiting(self) -> bool:
        return self._waiting_on is not None

    def stop(self) -> None:
        self.wait(None, lambda: None)
