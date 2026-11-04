# Security

## What leaves the machine

When the router is ON, each sized message is sent to `https://api.typesafe.ai` with your `TYPESAFE_API_KEY`, or,
when the Azure backend is configured (`JEV_AZURE_ENDPOINT` and `JEV_AZURE_DEPLOYMENT`), to that Azure AI Foundry
endpoint of yours with a Microsoft Entra token or `JEV_AZURE_API_KEY`. The text sent is the prompt as you typed it
(first 6000 characters). Nothing else goes to TypeSafe: the hook
never sends `transformedPrompt`, so the date, the workspace file listing and other context that Copilot adds
(VS Code adds a workspace tree) stay on your machine.

These messages are not sent to TypeSafe:

- slash commands (`/...`) and `!` shell commands;
- short follow-up replies, such as "yes" or "shorter", in a session that already sent a prompt;
- messages that match the built-in secret pattern (API keys, `password:`, private key blocks);
- every message while the router is OFF.

The secret pattern is a best-effort filter, not a guarantee. Keep the router OFF in any session where you paste
material you would not send to a third-party API.

Delegation is separate from sizing. When the router routes a message, the main model writes a self-contained
prompt for the helper agent, and that prompt goes to the helper's model through Copilot as usual.

## What is stored locally

- `~/.copilot/jev-router/state.json`: on/off switch, counters, Jev token totals, the last error, and the IDs of
  recent sessions. It never contains message text.
- `~/.copilot/jev-router/decisions.log`: one JSON line per sized message (route, probability, latency, character
  count, backend). It never contains message text.
- `~/.copilot/jev-router/azure-token.json` (Azure backend only): the cached Entra bearer token and its expiry, written
  owner-only (mode 600, atomic replace). It is a credential valid for about an hour. `uninstall.sh` removes the folder;
  delete the file yourself if you stop using the Azure backend earlier.
- Copilot session history, `~/.copilot/session-state/<sessionId>/events.jsonl`: the router rewrites the prompt
  that the model sees, so the rewritten text (the routing note, or the status echo for control phrases) is saved
  there as the user message's transformed content and is replayed on `--resume`. Treat `session-state` as
  sensitive, the same as your prompts. The note adds no message text of its own, but it is saved with the prompt.

## Fallback pieces (optional, Phase 3)

**`jevcp` passes the prompt on argv.** `jevcp` runs `jev_copilot.py size "<prompt>"` and then `copilot ... -p "<prompt>"`.
On a shared machine another local user can see the full prompt in `ps` while the process runs. The same applies to any
`copilot -p` call, but `jevcp` adds a second process that also carries it for a moment. `jevcp` never reads or prints
`TYPESAFE_API_KEY`. It is not installed on PATH; you add the folder yourself. `jevcp.ps1` behaves the same on Windows.

**The Tier 2 MCP server (`jev_mcp.py`) runs under the Copilot CLI.** Copilot starts it as your user with
`python3 -I jev_mcp.py` and talks to it over stdin and stdout. It reads and writes the same `state.json` and
`decisions.log` as the hook, and it sends the same prompt text (first 6000 characters, unless it is a secret,
short follow-up, or the router is OFF) to TypeSafe. Its tool result (the routing note) is part of the conversation,
the same as the hook's rewritten prompt. It is off until you register it in `~/.copilot/mcp-config.json` yourself.

**The status line (`jev_statusline.py`) reads only `state.json` and the last line of `decisions.log`.** It never reads
the stdin that Copilot sends, never sends network traffic, and prints only the router state, the route, and a
probability. It contains no message text. It is not registered until you add the `statusLine` entry to
`~/.copilot/settings.json` yourself.

## Your credentials

`TYPESAFE_API_KEY`, and for the Azure backend `JEV_AZURE_ENDPOINT`, `JEV_AZURE_DEPLOYMENT` and the optional
`JEV_AZURE_API_KEY`, are each read from the environment variable of that name. If that is unset, the router runs
`/usr/bin/security find-generic-password -w -s <NAME>` (macOS Keychain, 1 second timeout each). The hook
process gets the values in memory only; apart from the Azure token cache above, nothing is written to any file. The
installer never reads, copies, prints or stores them; `status` and `key` name the backend and the source of each value,
never the value. The Azure endpoint and deployment name are handled as secrets on purpose. Without `JEV_AZURE_API_KEY`
the router runs `az account get-access-token` with your Azure CLI login, outside the hook only. Store a value once,
and you are prompted for it so it stays out of shell history:

    security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w

Copilot's hooks can run without your shell environment (for example when VS Code starts from the Dock), which is
why the Keychain fallback exists. macOS may ask you once to allow `security` to read the item.

On Windows, `jev_compat.py` reads the generic credential named `TYPESAFE_API_KEY` from the Credential Manager with
`CredReadW` (your user's store, no elevation) when the environment variable is unset, and puts it into the
environment of the hook process only. Store it once; `Read-Host` keeps the value out of the command history:

    $k = Read-Host 'TypeSafe API key' -AsSecureString
    cmdkey /generic:TYPESAFE_API_KEY /user:$env:USERNAME /pass:((New-Object System.Net.NetworkCredential('', $k)).Password)

`jev_copilot.py key` reports where the key was found (environment, Keychain, Credential Manager) and never its value.

## Hooks run as you

`~/.copilot/hooks/jev-router.json` runs `python3 -I .../jev_copilot.py transform` as your user (on Windows the
`powershell` entry runs the same script through PowerShell 7 with the interpreter's full path). Whoever can write
to `~/.copilot/jev-router/` or to the hook file can run code as you on every prompt. Both CLI and VS Code read
the same `~/.copilot/hooks` folder, so this hook also runs in VS Code Copilot-harness sessions.

## Failures are silent

The hook fails open: on a timeout, an error, or bad input the message goes through unchanged and nothing is shown.
The error is recorded in `state.json`. Run `jev router status` to see `last error`.

## Reporting a vulnerability

Open a GitHub issue for anything that does not expose user data. For a report that does, use GitHub's private
vulnerability reporting on this repository instead of a public issue.

## Per-size model configuration

`models.json` holds model IDs, labels, effort and policy per size; no secrets. The `model` command and the chat
phrase `jev router model ...` rewrite it and re-render the matching `agents/jev-<size>.agent.md` from the template
in `jev-router/agents/`. Values are validated locally (ID shape, effort and policy enumerations, label length) before
anything is written; the rendered file is checked for leftover placeholders. The chat phrase is handled inside the
hook and never reaches Jev or the model as a task: the model only echoes the resulting table. A broken `models.json`
makes the hook fall back to the defaults (fail-open) and makes the `model` command exit 2 with the reason.
