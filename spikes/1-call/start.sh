#!/bin/sh
# The human check for spikes 1 and 3. See HUMAN-CHECK.md.
exec "$(dirname "$0")/py.sh" human.py "$@"
