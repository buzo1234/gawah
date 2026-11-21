#!/usr/bin/env bash
# What the GitHub CI job runs (.github/workflows/main.yml). Run it before a merge;
# .workmux.yaml's pre-merge hook does. Tests use the fakes only: no keys needed.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
uv run pytest -q
