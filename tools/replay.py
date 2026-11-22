"""Replay a recorded call (fixtures/<call>.json) into a running server, line by line.

    uv run python tools/replay.py fixtures/call_two_amounts.json --speed 10

--speed 1 is real time, 10 is ten times faster. --url defaults to http://localhost:8000.
--key (or GAWAH_ACCESS_KEY) is the access key of a public server, sent as X-Access-Key.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fakes.replayer import main  # noqa: E402

if __name__ == "__main__":
    main()
