# Jev model router for GitHub Copilot

Routes each GitHub Copilot message to the smallest model that can do the job well. [TypeSafe Jev](https://typesafe.ai)
sizes the job as tiny, everyday, large or hardest; one of four helper agents, each pinned to a model of your choice,
does it; the main model stays in charge of the conversation and relays the result. One install covers Copilot CLI
and VS Code (Copilot harness), because both read the same `~/.copilot` hooks and agents.

This is the Copilot port of [jev_router](https://github.com/TechPreacher/jev_router) for Claude Code. The routing
logic (`router.py`) is the same file, copied unchanged.

## Quick start

```bash
git clone https://github.com/TechPreacher/jev-router-copilot.git
cd jev-router-copilot/jev-router-copilot
./install.sh
```

Windows, from PowerShell:

```powershell
git clone https://github.com/TechPreacher/jev-router-copilot.git
cd jev-router-copilot\jev-router-copilot
.\install.ps1
```

Then, in a Copilot CLI or VS Code chat: `jev router on`. Every later message is sized by Jev and, when the call is
confident, handed to `jev-tiny`, `jev-everyday`, `jev-large` or `jev-hardest`. `jev router status` shows the counts,
`jev router off` stops routing. The installer never edits your `settings.json`.

Requirements: macOS, Linux or Windows (with PowerShell 7, which Copilot CLI uses for hooks there), Python 3.8+
(standard library only), GitHub Copilot CLI or VS Code with Copilot, and a TypeSafe API key in `TYPESAFE_API_KEY`,
the macOS Keychain or the Windows Credential Manager.

## Pick your models

Defaults: Claude Haiku 5.5 (tiny), Sonnet 5.5 (everyday), Opus 5.5 (large), Opus 5.5 at high effort (hardest).
Change any size at any time, also after installing:

```bash
python3 -I ~/.copilot/jev-router/jev_copilot.py model large gpt-6.1-sol
python3 -I ~/.copilot/jev-router/jev_copilot.py model reset
```

or `jev router model large gpt-6.1-sol` in chat. The next session uses it. `models` lists the models your account
can use, grouped by the size they fit (GitHub's own lightweight / versatile / powerful categories), so you can pick.

## Documentation

- [`jev-router-copilot/README.md`](jev-router-copilot/README.md): install, uninstall, control phrases, how it works,
  models, optional fallbacks (`jevcp` wrapper, MCP tool, status line), limits, privacy, testing.
- [`jev-router-copilot/SECURITY.md`](jev-router-copilot/SECURITY.md): what leaves the machine and when.
- Design notes, in reading order: [`01-analysis.md`](01-analysis.md) (the original router),
  [`02-copilot-capabilities.md`](02-copilot-capabilities.md) (what Copilot's hooks and agents can do),
  [`03-plan-copilot-cli.md`](03-plan-copilot-cli.md), [`04-plan-copilot-vscode.md`](04-plan-copilot-vscode.md),
  [`PROJECT-NOTES.md`](PROJECT-NOTES.md) (status log of the port).
- [`spikes/`](spikes/): the experiments that settled the open questions, with their evidence. Live end-to-end runs
  passed in Copilot CLI 1.0.105 and VS Code 1.144 (all four sizes), and for a changed per-size model.

## Status

Built and live-tested on macOS: the hook (Tier 1), the `jevcp` wrapper, per-size model configuration. Built and
offline-tested only: the MCP fallback (Tier 2), the status line, and Windows support (PowerShell installer, `jevcp.ps1`,
Credential Manager key, hook `powershell` entry). Not built: a VS Code companion extension.
69 offline unit tests run in CI on Ubuntu, macOS and Windows.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security policy:
[SECURITY.md](SECURITY.md). Licensed under the [MIT License](LICENSE).
