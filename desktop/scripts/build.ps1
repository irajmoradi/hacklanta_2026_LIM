# Windows native build. Pass --dry-run for an unpacked application.
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm run build -- @args
    exit $LASTEXITCODE
} finally { Pop-Location }
