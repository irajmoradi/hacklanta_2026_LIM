# EXPLICIT LIVE SMOKE launcher: secret travels over SSH stdin, never a file/argument.
param([switch]$RetryFailed)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runner = (Get-Content (Join-Path $repo 'tools/runner_ip') -Raw).Trim()
$name = Split-Path $repo -Leaf
$keyLine = Get-Content 'C:/Users/mourn/Downloads/hacklanta/.env' | Where-Object { $_ -match '^GOOGLE_API_KEY=' } | Select-Object -First 1
if (-not $keyLine) { throw 'GOOGLE_API_KEY missing' }
$apiKey = ($keyLine -replace '^GOOGLE_API_KEY=', '').Trim().Trim('"').Trim("'")
try {
    $retryArg = if ($RetryFailed) { ' --retry-failed' } else { '' }
    $apiKey | & ssh -o BatchMode=yes -o ConnectTimeout=15 -i "$env:USERPROFILE/.ssh/village_vultr" "root@$runner" "cd /srv/lim/$name && .venv/bin/python demo_video/thumb/live_smoke.py$retryArg"
    $result = $LASTEXITCODE
} finally {
    $apiKey = $null
    $keyLine = $null
}
exit $result
