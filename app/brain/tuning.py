"""Every gap, limit and timeout the brain uses. Tune the Judge here and nowhere else.

Times that pace the Judge are in call seconds (the `end` of a transcript line), not wall
clock, so a call replayed at any speed behaves the same.
"""

# --- How often the Judge may speak (call seconds) ---
MIN_GAP_S = 15.0  # between the end of one question and the next mid-call interruption
WRAPUP_GAP_S = 3.0  # the same, once they are wrapping up: they are about to hang up
SPEAK_TIMEOUT_S = 12.0  # no judge.spoke by then: assume it was said and move on
WRAPUP_HOLD_S = 30.0  # how long "they are wrapping up" stays true after Sage2 last said so

# --- A pause in the talk ---
# Nobody has spoken for this long after a line (call seconds, from its end to the next line's start):
# a question about the record that nobody answered is Gawah's; a term brought up and left there is
# asked about; just after a term settles, the terms still open are named. Phone talk runs lines
# 0.5 to 2 s apart; the user's own calls left 3 to 10 s where they waited for Gawah.
PAUSE_S = 2.5
# On a live call a line reaches the brain about a second after it ends, so its timer runs this long
# (wall clock) from when the line arrives.
PAUSE_AFTER_LINE_S = 1.5
# The terms still open are named only at a pause within this many lines of a term settling.
SETTLED_LINES = 1

# --- When they are wrapping up ---
# Sage2's wrapping_up (a goodbye) is enough on its own. Its closing_soon comes earlier but
# has said yes alone mid-call, on talk about when the work starts, so it counts only
# twice in a row with no term settled on those two lines, or followed by a silence.
# Either way only once most of the deal is agreed: closing_soon said yes twice mid-call
# on the dry run with three of six terms agreed.
CLOSE_MIN_AGREED = 4  # of the six items, for closing_soon twice in a row
# For closing_soon then a silence, a term one person stated and nobody accepted yet counts
# too: the memory's facts hear fewer yeses than were said, and on the dry run only three
# terms were agreed by its last line, so it never wrapped up. Five, not four: closing_soon
# said yes mid-call on the dry run at line 17, before a long pause, with four discussed.
CLOSE_MIN_DISCUSSED = 5
# closing_soon, then no new line for this long (wall clock) while the Judge is not
# speaking. Lines in a lively call arrive 5 to 8 s apart (the dry run).
CLOSING_SILENCE_S = 10.0

# --- Changes ---
# A change offered to an agreed term is held while they bargain ("bees", "baarah", "pandrah"). With this
# many lines since the last offer and no counter or acceptance, the bargaining is over: Gawah asks both
# to agree to it (change_proposed). Accepted with its figure said back, the memory records it, nothing is asked.
CHANGE_SETTLE_LINES = 2

# --- How often it may ask ---
MAX_ASKS_PER_ITEM = 2  # in practice one mid-call and one at wrap-up
# A question the mouth dropped (no pause came) was never heard, so it does not count as an
# ask. It may be asked again mid-call this many times; wrap-up asks it regardless.
MAX_REASKS = 1

# --- Names ---
# A name the call did not start with is looked for after each of the first lines,
# where Gawah's opening line asks each person to say theirs.
NAME_LINES = 6

# --- The memory's facts ---
# The checklist comes from the memory's facts. If it has sent none from this call's lines
# by this many lines (its model is down, or there is no memory), every term would look open,
# so the Judge asks nothing at wrap-up and reads nothing back. On the practice calls the
# first fact comes by line 7.
MEMORY_SILENT_LINES = 12

# --- The OpenAI model: names, the term left unclear, two meanings ---
VALUES_MODEL = "gpt-5.4-mini"
# "none" is about half a second faster and got dates and sums wrong on the practice calls.
VALUES_EFFORT = "low"
VALUES_TIMEOUT_S = 6.0  # wall clock, per try; one retry
VALUES_RETRY_AFTER_S = 0.5
# The Judge's question waits this long (wall clock) for the model to name the term left
# unclear. After that it does not ask. The two-meanings check never holds a line up.
LOOKUP_WAIT_S = 4.0
END_WAIT_S = 8.0  # at call.ended, wait this long for model replies still on their way

# --- Sage2 (wall clock) ---
SAGE_OPEN_TIMEOUT_S = 10.0
SAGE_TIMEOUT_S = 3.0  # no answer for a line by then: keep the previous answers
SAGE_REOPENS = 2  # times a dropped stream is reopened in one call; after that the brain goes quiet
