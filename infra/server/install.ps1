param([string]$DataDir = "$env:LOCALAPPDATA\CaseQuarryServer", [string]$PostgresBin = "")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$serverArguments = @("server.py", "install", "--data-dir", $DataDir)
if ($PostgresBin) { $serverArguments += @("--postgres-bin", $PostgresBin) }
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run --no-project --python 3.12 python @serverArguments
} else {
    & py -3.12 @serverArguments
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
