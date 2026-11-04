#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
Install the Model router for GitHub Copilot from PowerShell. PowerShell twin of install.sh, for Windows
(it also runs under pwsh on macOS and Linux). Copilot CLI and the VS Code Copilot harness both read ~\.copilot.
  .\install.ps1                      installs into ~\.copilot
  $env:COPILOT_HOME = 'D:\dir'       then .\install.ps1 installs into D:\dir instead
  .\install.ps1 -Tier2               also installs the Tier 2 fallback (router_mcp.py + sessionStart hook)
If scripts are blocked:  pwsh -ExecutionPolicy Bypass -File .\install.ps1
Safe to re-run: files are updated in place, a changed file is first kept as <name>.bak-<timestamp>, and the
hook file is rewritten from the template. A fresh install leaves the router OFF. An existing on/off switch and
its stats are kept. Nothing is sent to TypeSafe during install. The installer never writes settings.json,
mcp-config.json or your PowerShell profile: it prints the snippets and the PATH line for you to add.
On Windows the hook and the skill call the Python interpreter by its full path, resolved here (python, python3
or py -3, whichever works first), because Copilot runs hooks with pwsh and a bare name may hit the Store stub.
Copilot CLI needs PowerShell 7 (pwsh) on PATH to run hooks on Windows; this script itself runs on 5.1 too.
#>
[CmdletBinding()]
param([switch]$Tier2)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$OnWindows = [System.Environment]::OSVersion.Platform -eq 'Win32NT'
$Here = $PSScriptRoot
$Src = Join-Path $Here 'files'
$CP = if ($env:COPILOT_HOME) { $env:COPILOT_HOME } else { Join-Path $HOME '.copilot' }
$JR = Join-Path $CP 'model-router'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ('router-install-' + [System.IO.Path]::GetRandomFileName())
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$SavedEnv = @{ COPILOT_HOME = $env:COPILOT_HOME; MODEL_ROUTER_HOME = $env:MODEL_ROUTER_HOME }

function Invoke-Python {
    # & python with the given arguments; stdin from -StdIn when given. Sets $script:LastRc. Never throws on exit code.
    param([string[]]$Arguments, [string]$StdIn = $null)
    $ErrorActionPreference = 'Continue'
    if ($null -ne $StdIn) { $out = $StdIn | & $PyExe @Arguments 2>&1 } else { $out = & $PyExe @Arguments 2>&1 }
    $script:LastRc = $LASTEXITCODE
    return (@($out) | ForEach-Object { "$_" }) -join "`n"
}

function Find-Python {
    # The first of python, python3, py -3 that is a working Python 3.8+. Returns its executable path.
    $ErrorActionPreference = 'Continue'
    foreach ($candidate in @(@('python'), @('python3'), @('py', '-3'))) {
        if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
        $extra = @($candidate | Select-Object -Skip 1)
        $exe = & $candidate[0] @extra -I -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return @($exe)[0].Trim() }
    }
    return $null
}

function Install-File([string]$Source, [string]$Dest) {
    # Copy unless identical; a changed destination is kept as <name>.bak-<timestamp> first.
    if (Test-Path -LiteralPath $Dest) {
        if ((Get-FileHash -LiteralPath $Source).Hash -eq (Get-FileHash -LiteralPath $Dest).Hash) { return }
        $leaf = Split-Path -Leaf $Dest
        Copy-Item -LiteralPath $Dest -Destination "$Dest.bak-$Stamp"
        Write-Output "  kept previous $leaf as $leaf.bak-$Stamp"
    }
    Copy-Item -LiteralPath $Source -Destination $Dest
}

function ConvertTo-JsonText([string]$Text) {
    # The JSON string escape of Text, without the surrounding quotes.
    $quoted = $Text | ConvertTo-Json
    return $quoted.Substring(1, $quoted.Length - 2)
}

function Write-Rendered([string]$Template, [string]$Dest) {
    # Replaces @JR@ with the install dir and @PY@ with the interpreter command. A .json output is escaped and validated.
    $text = [System.IO.File]::ReadAllText($Template, [System.Text.Encoding]::UTF8)
    if ($Dest.EndsWith('.json')) {
        $text = $text.Replace('@JR@', (ConvertTo-JsonText $JR)).Replace('@PY@', (ConvertTo-JsonText $PyCmd))
        $null = $text | ConvertFrom-Json
    } else {
        $text = $text.Replace('@JR@', $JR).Replace('@PY@', $PyCmd)
    }
    [System.IO.File]::WriteAllText($Dest, $text, $Utf8)
}

$PyExe = Find-Python
if (-not $PyExe) {
    Write-Error 'python not found. Install Python 3.8+ first (winget install Python.Python.3.13, or python.org) and reopen the terminal.'
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $Src 'router.py'))) {
    Write-Error "$Src\router.py not found. Run install.ps1 from the project checkout."
    exit 1
}
# The command the hook, the skill and the snippets use. Windows: the full path, so VS Code and the CLI agree.
$PyCmd = if ($OnWindows) { '& "' + $PyExe + '"' } else { 'python3' }
$PyName = if ($OnWindows) { $PyExe } else { 'python3' }  # for the MCP snippet, which takes an executable
$Adapter = Join-Path $JR 'router_copilot.py'
$ModelsFile = Join-Path $JR 'models.json'
$StatusScript = Join-Path $JR 'router_statusline.py'
$McpScript = Join-Path $JR 'router_mcp.py'

try {
    Write-Output "Installing Model router into $CP"
    # An install made under the old name (jev-router) moves over: models.json, state and stats are kept, the old hook,
    # agents, skill and scripts are removed. settings.json and mcp-config.json are never touched (a note follows).
    $OldJR = Join-Path $CP 'jev-router'
    $Migrated = $false
    if ((Test-Path -LiteralPath $OldJR) -and -not (Test-Path -LiteralPath $JR)) {
        if ((Test-Path -LiteralPath (Join-Path $OldJR 'jev_mcp.py')) -or (Test-Path -LiteralPath (Join-Path $CP 'hooks\jev-router-session.json'))) {
            $Tier2 = $true  # the old install had the Tier 2 fallback; keep it under the new names
        }
        Move-Item -LiteralPath $OldJR -Destination $JR
        foreach ($pattern in @('jev_*.py', 'bin\jevcp', 'bin\jevcp.ps1', 'agents\jev-*.agent.md.tmpl')) {
            Get-ChildItem -Path (Join-Path $JR $pattern) -ErrorAction SilentlyContinue | Remove-Item -Force
        }
        foreach ($f in @('hooks\jev-router.json', 'hooks\jev-router-session.json', 'agents\jev-tiny.agent.md',
                         'agents\jev-everyday.agent.md', 'agents\jev-large.agent.md', 'agents\jev-hardest.agent.md')) {
            Remove-Item -LiteralPath (Join-Path $CP $f) -Force -ErrorAction SilentlyContinue
        }
        $oldSkill = Join-Path $CP 'skills\jev-router'
        if (Test-Path -LiteralPath $oldSkill) { Remove-Item -LiteralPath $oldSkill -Recurse -Force }
        $Migrated = $true
        Write-Output "  migrated the jev-router install to $JR (models.json, state and stats kept; old hook, agents, skill and scripts removed)"
    }
    $null = New-Item -ItemType Directory -Force -Path $Stage, (Join-Path $Stage 'agents'), (Join-Path $Stage 'selftest')
    $null = New-Item -ItemType Directory -Force -Path (Join-Path $JR 'bin'), (Join-Path $JR 'agents'), (Join-Path $CP 'agents'), (Join-Path $CP 'hooks'), (Join-Path $CP 'skills\model-router')

    foreach ($name in @('router.py', 'router_copilot.py', 'router_compat.py', 'router_statusline.py')) {
        Install-File (Join-Path $Src $name) (Join-Path $JR $name)
    }
    Install-File (Join-Path $Src 'bin\routercp') (Join-Path $JR 'bin\routercp')
    Install-File (Join-Path $Src 'bin\routercp.ps1') (Join-Path $JR 'bin\routercp.ps1')
    if (-not $OnWindows -and (Get-Command chmod -ErrorAction SilentlyContinue)) {
        & chmod 755 (Join-Path $JR 'bin\routercp') (Join-Path $JR 'router_statusline.py')
    }
    # Agent files are rendered from templates and models.json (per-size model, effort, policy, label).
    # The templates are installed too, so `router_copilot.py model ...` can re-render an agent file later.
    # An existing models.json is never overwritten: a re-install keeps the user's model choices.
    foreach ($tmpl in Get-ChildItem -LiteralPath (Join-Path $Src 'agents') -Filter 'router-*.agent.md.tmpl') {
        Install-File $tmpl.FullName (Join-Path $JR ('agents\' + $tmpl.Name))
    }
    $env:COPILOT_HOME = $CP
    $null = Invoke-Python @('-I', $Adapter, 'render-agents', (Join-Path $Stage 'agents'))
    if ($LastRc -ne 0) { throw "render-agents failed (exit $LastRc)" }
    foreach ($agent in Get-ChildItem -LiteralPath (Join-Path $Stage 'agents') -Filter 'router-*.agent.md') {
        Install-File $agent.FullName (Join-Path $CP ('agents\' + $agent.Name))
    }

    Write-Rendered (Join-Path $Src 'hooks\model-router.json.tmpl') (Join-Path $Stage 'model-router.json')
    Install-File (Join-Path $Stage 'model-router.json') (Join-Path $CP 'hooks\model-router.json')
    Write-Rendered (Join-Path $Src 'skills\model-router\SKILL.md') (Join-Path $Stage 'SKILL.md')
    Install-File (Join-Path $Stage 'SKILL.md') (Join-Path $CP 'skills\model-router\SKILL.md')

    if ($Tier2) {
        Install-File (Join-Path $Src 'router_mcp.py') (Join-Path $JR 'router_mcp.py')
        Write-Rendered (Join-Path $Src 'hooks\model-router-session.json.tmpl') (Join-Path $Stage 'model-router-session.json')
        Install-File (Join-Path $Stage 'model-router-session.json') (Join-Path $CP 'hooks\model-router-session.json')
        Write-Output '  Tier 2 installed (session hook + router_mcp.py). It is NOT registered yet; see the snippet below.'
    }

    # Fresh install: OFF. A re-install keeps whatever on/off state and stats the user already has.
    if (-not (Test-Path -LiteralPath (Join-Path $JR 'state.json'))) {
        $null = Invoke-Python @('-I', $Adapter, 'off')
        if ($LastRc -ne 0) { throw "could not write the initial state (exit $LastRc)" }
    }

    # Self-test in a scratch state dir, which is OFF by default, so nothing is sent anywhere.
    # The hook must print nothing and exit 0. The status line must print "Router OFF".
    $env:MODEL_ROUTER_HOME = Join-Path $Stage 'selftest'
    $payload = '{"sessionId":"install-selftest","prompt":"install self-test","transformedPrompt":"install self-test"}'
    $out = Invoke-Python @('-I', $Adapter, 'transform') -StdIn $payload
    $rc = $LastRc
    $line = Invoke-Python @('-I', (Join-Path $JR 'router_statusline.py')) -StdIn ''
    $env:MODEL_ROUTER_HOME = $SavedEnv.MODEL_ROUTER_HOME
    if ($rc -ne 0 -or $out) {
        Write-Output "error: self-test failed (exit $rc, output: $out). Files are installed; fix this before using the router."
        exit 1
    }
    if ($line.Trim() -ne 'Router OFF') {
        Write-Output "error: status line self-test printed '$line' instead of 'Router OFF'. Files are installed; check router_statusline.py."
        exit 1
    }

    $status = Invoke-Python @('-I', $Adapter, 'status')
    Write-Output ''
    Write-Output "Self-test passed (hook is silent while OFF, exit 0; status line prints 'Router OFF')."
    Write-Output ('Done. ' + @($status -split "`n")[0])
    if ($Migrated) {
        foreach ($f in @((Join-Path $CP 'settings.json'), (Join-Path $CP 'mcp-config.json'))) {
            if ((Test-Path -LiteralPath $f) -and (Select-String -LiteralPath $f -Pattern 'jev-router/' -SimpleMatch -Quiet)) {
                Write-Output "NOTE: $f still points at jev-router/; change that path to model-router/ (and jev_statusline.py to router_statusline.py, jev_mcp.py to router_mcp.py) yourself."
            }
        }
    }

    $keyReport = Invoke-Python @('-I', $Adapter, 'key')
    if ($LastRc -ne 0) {
        Write-Output $keyReport
        if ($OnWindows) {
            Write-Output @'

NOTE: the active backend lacks a credential (see above), so the router cannot size messages. For TypeSafe, store the
key once as a generic credential (you are prompted for the value, so it stays out of the command history):
    $k = Read-Host 'TypeSafe API key' -AsSecureString
    cmdkey /generic:TYPESAFE_API_KEY /user:$env:USERNAME /pass:((New-Object System.Net.NetworkCredential('', $k)).Password)
For an Azure Decision-1 deployment, store MODEL_ROUTER_AZURE_ENDPOINT and MODEL_ROUTER_AZURE_DEPLOYMENT the same way and run `az login`.
'@
        } else {
            Write-Output @'

NOTE: the active backend lacks a credential (see above), so the router cannot size messages. For TypeSafe, store the
key once (you are prompted for the value, so it stays out of shell history):
    security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w
For an Azure Decision-1 deployment, store MODEL_ROUTER_AZURE_ENDPOINT and MODEL_ROUTER_AZURE_DEPLOYMENT the same way and run `az login`.
'@
        }
    }

    $bin = Join-Path $JR 'bin'
    Write-Output @"

Next steps:
  1. Start Copilot CLI (copilot), or open a Copilot-harness chat in VS Code.
  2. Type:  model router on        (also: model router off | status | reset | model ...)
  Shell:    $PyCmd -I "$Adapter" on|off|status|reset|model
  Models:   $PyCmd -I "$Adapter" model <size> <model-id>    (or in chat: model router model <size> <model-id>)
            changes one size's model and re-renders its agent file in place; 'model' alone shows the table,
            'models' lists the models your account can use, grouped by the size they fit (chat: model router models).
            Your choices live in $ModelsFile and survive re-installs.
  Key:      $PyCmd -I "$Adapter" key    (says where TYPESAFE_API_KEY was found, never its value)
  Remove:   .\uninstall.ps1      (with the same COPILOT_HOME, if you set one)

Optional, not written by the installer:
  routercp (Tier 3): add the bin folder to PATH yourself, for example
    this session:  `$env:PATH = "$bin;`$env:PATH"
    permanently:   [Environment]::SetEnvironmentVariable('PATH', "$bin;" + [Environment]::GetEnvironmentVariable('PATH', 'User'), 'User')
  Use:      routercp "prompt"    or    routercp -i "prompt"      (runs routercp.ps1)
"@

    $statusLine = [ordered]@{ statusLine = [ordered]@{ type = 'command'; command = "$PyCmd -I `"$StatusScript`"" } }
    Write-Output ''
    Write-Output 'statusLine: paste into ~\.copilot\settings.json (top level):'
    Write-Output ($statusLine | ConvertTo-Json -Depth 4)

    if ($Tier2) {
        $mcp = [ordered]@{ mcpServers = [ordered]@{ 'model-router' = [ordered]@{ type = 'local'; command = $PyName; args = @('-I', $McpScript); tools = @('*') } } }
        Write-Output ''
        Write-Output 'Tier 2 MCP server: merge this into ~\.copilot\mcp-config.json (keep your other servers):'
        Write-Output ($mcp | ConvertTo-Json -Depth 6)
        Write-Output 'Use Tier 2 only if the userPromptTransformed hook (Tier 1) stops working: both would size each message.'
    }
} finally {
    $env:COPILOT_HOME = $SavedEnv.COPILOT_HOME
    $env:MODEL_ROUTER_HOME = $SavedEnv.MODEL_ROUTER_HOME
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue }
}
