$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
uv run python scripts/tasks.py dev
exit $LASTEXITCODE
