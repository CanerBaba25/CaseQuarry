param([string]$Server = 'http://127.0.0.1:8000', [string]$Web = 'http://127.0.0.1:3000')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
uv run python scripts/tasks.py smoke --server $Server --web $Web
exit $LASTEXITCODE
