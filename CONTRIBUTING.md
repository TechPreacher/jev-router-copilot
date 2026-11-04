# Contributing

Thanks for helping improve the Model router for GitHub Copilot.

## Ground rules

- Keep the hook fast and silent. Every failure path in `model-router-copilot/files/router_copilot.py` must print nothing
  and exit 0 within the 3-second hook timeout. A hook that blocks or slows a message is a bug, even if it is "correct".
- `files/router.py` is a verbatim copy of [model-router](https://github.com/TechPreacher/model-router). Fix routing logic
  upstream, then copy the file; keep the Copilot-specific code in the adapter. Platform shims the core needs (the
  `fcntl` stand-in on Windows, the Credential Manager key) live in `files/router_compat.py`, not in a patched core.
- No new dependencies. Stock Python 3.8+ (macOS, Linux or Windows), standard library only.
- Never log or store the user's message text. `decisions.log` records route, probability and latency; keep it that way.
- Scripts come in pairs: bash with `#!/usr/bin/env bash` and POSIX-style tests (`=`, not `==`), and a PowerShell twin
  (`install.ps1`, `uninstall.ps1`, `routercp.ps1`, `tests/run.ps1`) that must stay in step and run on PowerShell 5.1 and 7.
  Test the installers against a temporary `COPILOT_HOME` as well as a real `~/.copilot` that has other hooks.
- Never touch `~/.copilot/settings.json`, `config.json` or `mcp-config.json` from the installer; print snippets instead.

## Workflow

1. Fork and branch from `main`.
2. Make your change in `model-router-copilot/`. Run the checks CI runs:
   ```bash
   cd model-router-copilot
   python3 -I -m py_compile files/*.py tests/*.py
   bash -n install.sh uninstall.sh files/bin/routercp
   bash tests/run.sh          # Windows: pwsh -File tests/run.ps1
   ```
   The tests are offline: a fake Jev server on 127.0.0.1 and a stub `copilot` on PATH. They never run the real CLI.
   `test_pwsh.py` runs wherever `pwsh` is installed (it is on every GitHub runner) and parses all `.ps1` files.
3. Try the adapter by hand against a scratch home:
   ```bash
   export COPILOT_HOME=/tmp/router-test MODEL_ROUTER_HOME=/tmp/router-test/model-router
   mkdir -p "$MODEL_ROUTER_HOME"
   python3 -I files/router_copilot.py on
   printf '{"sessionId":"x","prompt":"rename foo to bar","transformedPrompt":"rename foo to bar"}' | \
     python3 -I files/router_copilot.py transform
   python3 -I files/router_copilot.py status
   ```
4. Add or update a test in `tests/` for behaviour you change. Live Copilot runs cost credits; they are manual
   (see "Testing" in `model-router-copilot/README.md`) and the evidence goes into a `spikes/*.md` write-up, never raw
   session files.
5. Open a pull request. Say what changed and why; keep it small.

## Reporting issues

Use GitHub issues. Include your OS, Copilot CLI or VS Code version, the output of
`python3 -I ~/.copilot/model-router/router_copilot.py status` and `... model`, and the relevant lines from
`~/.copilot/model-router/decisions.log` (they contain no message text). Never paste your `TYPESAFE_API_KEY`, your
`~/.copilot/settings.json` or a Copilot `events.jsonl` file.
