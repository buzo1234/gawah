#!/bin/sh
# Runs a spike script with the two packages the project does not have yet (livekit, livekit-api).
# If a local wheel folder exists (made when uv could not reach PyPI), use it offline.
cd "$(dirname "$0")"
if [ -d .wheels ]; then
  exec uv run --offline --find-links .wheels --with livekit --with livekit-api python -u "$@"
fi
exec uv run --with livekit --with livekit-api python -u "$@"
