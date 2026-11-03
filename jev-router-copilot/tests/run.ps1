#!/usr/bin/env pwsh
# Offline test suite from PowerShell: stdlib unittest only. The only server is tests/fake_jev.py on 127.0.0.1.
# PowerShell twin of tests/run.sh. PYTHONUTF8 keeps the test harness itself on UTF-8 on Windows.
$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = '1'
foreach ($candidate in @(@('python'), @('python3'), @('py', '-3'))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @($candidate | Select-Object -Skip 1)
    & $candidate[0] @extra -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) {
        & $candidate[0] @extra -m unittest discover -s tests -v
        exit $LASTEXITCODE
    }
}
[Console]::Error.WriteLine('error: no Python 3.8+ found (tried python, python3, py -3).')
exit 1
