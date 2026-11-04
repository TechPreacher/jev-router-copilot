#!/usr/bin/env pwsh
# routercp.ps1: size a prompt with the sizing backend, then run Copilot CLI on the model it picked (Tier 3 fallback).
# PowerShell twin of routercp, for Windows (it also runs under pwsh on macOS and Linux).
#   routercp [-i] "prompt"          -i starts an interactive session with the prompt (default: one-shot -p)
#   routercp -Prompt "-starts with a dash"     (PowerShell has no `--`; a prompt that starts with - needs -Prompt)
# Routes the main model, which the Tier 1 hook cannot do. When the router is OFF, or the sizing backend keeps the
# prompt with the main model, copilot runs on its default model. The prompt is passed on the command
# line, so it is visible to other users on this machine while copilot runs.
# Installed to $COPILOT_HOME\model-router\bin\routercp.ps1, next to router_copilot.py.
[CmdletBinding()]
param(
    [switch]$i,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Prompt
)

$ErrorActionPreference = 'Continue'
$JR = Split-Path -Parent $PSScriptRoot

function Find-Python {
    # The first of python, python3, py -3 that is a working Python 3.8+. Returns its executable path.
    foreach ($candidate in @(@('python'), @('python3'), @('py', '-3'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        $exe = & $candidate[0] @extra -I -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return @($exe)[0].Trim() }
    }
    return $null
}

$text = ($Prompt -join ' ').Trim()
if (-not $text) { [Console]::Error.WriteLine('usage: routercp [-i] "prompt"   (or -Prompt "..." for a prompt that starts with -)'); exit 2 }

# One call sizes the prompt and records the decision. Any failure means: default model.
$line = 'local - -'
$py = Find-Python
if ($py) {
    $out = & $py -I (Join-Path $JR 'router_copilot.py') size $text 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { $line = @($out)[0] }
}
$parts = @($line.Trim() -split ' +') + @('-', '-', '-')
$route, $model, $effort = $parts[0], $parts[1], $parts[2]
if (-not $route) { $route = 'local' }

$extra = @()
if ($route -in @('tiny', 'everyday', 'large', 'hardest')) {
    [Console]::Error.WriteLine("routercp: $route -> $model")
    $extra += @('--model', $model)
    if ($effort -ne '-') { $extra += @('--reasoning-effort', $effort) }
} else {
    [Console]::Error.WriteLine("routercp: $route -> default model")
}

# The hook would size this prompt a second time inside copilot. Tell it not to. A script shares the calling
# PowerShell session's environment, so the flag is restored afterwards; otherwise a later plain `copilot` in the
# same window would skip sizing too.
$saved = $env:MODEL_ROUTER_PRESIZED
$rc = 1
try {
    $env:MODEL_ROUTER_PRESIZED = '1'
    $mode = if ($i) { '-i' } else { '-p' }
    & copilot @extra $mode $text
    $rc = $LASTEXITCODE
} finally {
    $env:MODEL_ROUTER_PRESIZED = $saved
}
exit $rc
