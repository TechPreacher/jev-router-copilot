#!/usr/bin/env pwsh
#Requires -Version 5.1
# Remove what install.ps1 (or install.sh) added from $env:COPILOT_HOME, default ~\.copilot: the hook files (Tier 1
# and Tier 2), the four helper agents, the jev-router skill, and the jev-router directory (router core, adapter,
# compat shims, status line, jevcp, the Tier 2 MCP server, the agent templates, models.json, state.json and
# decisions.log with the stats). Empty folders that the installer created are removed. Other Copilot files are
# not touched. Backups (*.bak-<timestamp>) are listed, not deleted. PowerShell twin of uninstall.sh.
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$CP = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME '.copilot' }
$JR = Join-Path $CP 'jev-router'

foreach ($f in @('hooks\jev-router.json', 'hooks\jev-router-session.json')) {
    Remove-Item -LiteralPath (Join-Path $CP $f) -Force -ErrorAction SilentlyContinue
}
foreach ($size in @('tiny', 'everyday', 'large', 'hardest')) {
    Remove-Item -LiteralPath (Join-Path $CP "agents\jev-$size.agent.md") -Force -ErrorAction SilentlyContinue
}
foreach ($d in @((Join-Path $CP 'skills\jev-router'), $JR)) {
    if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }
}
foreach ($d in @('skills', 'hooks', 'agents')) {  # only removes empty folders
    $p = Join-Path $CP $d
    if ((Test-Path -LiteralPath $p) -and -not (Get-ChildItem -LiteralPath $p -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $p -Force
    }
}

Write-Output "Jev router removed from $CP (hook files, helper agents, skill, and $JR with its models.json, state and stats)."
$backups = @()
foreach ($d in @('agents', 'hooks')) {
    $p = Join-Path $CP $d
    if (Test-Path -LiteralPath $p) {
        $backups += Get-ChildItem -LiteralPath $p -File | Where-Object { $_.Name -like 'jev-*.bak-*' } | ForEach-Object { $_.FullName }
    }
}
if ($backups.Count -gt 0) {
    Write-Output 'Backups made by the installer were kept. Delete them yourself if you no longer need them:'
    $backups | ForEach-Object { Write-Output $_ }
}
# The installer never writes these two files, so remove the entries yourself if you pasted them.
$mcp = Join-Path $CP 'mcp-config.json'
if ((Test-Path -LiteralPath $mcp) -and (Select-String -LiteralPath $mcp -Pattern 'jev_mcp.py' -SimpleMatch -Quiet)) {
    Write-Output "Remove the jev-router entry from $mcp yourself (the Tier 2 MCP server)."
}
$settings = Join-Path $CP 'settings.json'
if ((Test-Path -LiteralPath $settings) -and (Select-String -LiteralPath $settings -Pattern 'jev_statusline.py' -SimpleMatch -Quiet)) {
    Write-Output "Remove the statusLine entry from $settings yourself (it points at jev_statusline.py)."
}
