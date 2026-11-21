"""Every gap, limit and timeout the brain uses. Tune the Judge here and nowhere else.

Times that pace the Judge are in call seconds (the `end` of a transcript line), not wall
clock, so a call replayed at any speed behaves the same.
"""

# --- How often the Judge may speak (call seconds) ---
MIN_GAP_S = 15.0  # between the end of one question and the next mid-call interruption
WRAPUP_GAP_S = 3.0  # the same, once they are wrapping up: they are about to hang up
SPEAK_TIMEOUT_S = 12.0  # no judge.spoke by then: assume it was said and move on
WRAPUP_HOLD_S = 30.0  # how long "they are wrapping up" stays true after Sage2 last said so

# --- How often it may ask ---
MAX_ASKS_PER_ITEM = 2  # in practice one mid-call and one at wrap-up
# An answered question is checked this many lines after the Judge asked it, so that
# both people have had a turn.
RESOLVE_AFTER_LINES = 2

# --- Values from the OpenAI model ---
VALUES_MODEL = "gpt-5.4-mini"
# "none" is about half a second faster and got dates and sums wrong on the practice calls.
VALUES_EFFORT = "low"
VALUES_TIMEOUT_S = 6.0  # wall clock, per try; one retry
VALUES_RETRY_AFTER_S = 0.5
VALUE_TRIES = 3  # per item, when the model says the term is not settled yet
VALUE_RETRY_LINES = 2  # lines to wait before trying again
# The Judge's question waits this long (wall clock) for the model to name the term and
# the two figures. After that it asks without them.
LOOKUP_WAIT_S = 4.0
END_WAIT_S = 8.0  # at call.ended, wait this long for values still on their way

# --- Sage2 (wall clock) ---
SAGE_OPEN_TIMEOUT_S = 10.0
SAGE_TIMEOUT_S = 3.0  # no answer for a line by then: keep the previous answers
SAGE_REOPENS = 2  # times a dropped stream is reopened in one call; after that the brain goes quiet
