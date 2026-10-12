#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec uv run python scripts/tasks.py smoke "$@"
