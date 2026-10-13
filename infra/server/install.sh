#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if command -v uv >/dev/null 2>&1; then
    exec uv run --no-project --python 3.12 python server.py install "$@"
fi
exec python3.12 server.py install "$@"
