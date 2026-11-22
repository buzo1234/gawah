"""The Sentinel's tuning values. Each can be set in the shell (not read from .env)."""

import os

# After the work is confirmed done with money still owed: how long before the hirer is
# reminded. 60 seconds for the demo; a real deal would wait a day or more.
BALANCE_REMINDER_SECONDS = float(os.environ.get("SENTINEL_BALANCE_REMINDER_SECONDS", "60"))

# A date the deal names (the advance or the balance "by Monday") has passed once that day is
# over in India; the reminder goes this many hours into the next day, not at midnight.
DATE_REMINDER_HOURS_AFTER = float(os.environ.get("SENTINEL_DATE_REMINDER_HOURS_AFTER", "9"))

# A term disputed on a call-back and still open: one reminder to both after this long, with the
# choices again (two days; tests set it short).
DISPUTE_REMINDER_SECONDS = float(os.environ.get("SENTINEL_DISPUTE_REMINDER_SECONDS", str(2 * 24 * 3600)))
