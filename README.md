# Model router for GitHub Copilot

Routes each GitHub Copilot message to the smallest model that can do the job well. [TypeSafe Jev](https://typesafe.ai)
or Microsoft Decision-1 in Azure sizes the job as tiny, everyday, large or hardest; one of four helper agents, each pinned to a model of your choice,
does it; the main model stays in charge of the conversation and relays the result. One install covers Copilot CLI
and VS Code (Copilot harness), because both read the same `~/.copilot` hooks and agents.

This is the Copilot port of [model-router](https://github.com/TechPreacher/model-router) for Claude Code. The routing
logic (`router.py`) is the same file, copied unchanged.

## Quick start

```bash
git clone https://github.com/TechPreacher/model-router-copilot.git
cd model-router-copilot/model-router-copilot
./install.sh
```

Windows, from PowerShell:

```powershell
git clone https://github.com/TechPreacher/model-router-copilot.git
cd model-router-copilot\model-router-copilot
.\install.ps1
```

Then, in a Copilot CLI or VS Code chat: `model router on`. Every later message is sized by Jev and, when the call is
confident, handed to `router-tiny`, `router-everyday`, `router-large` or `router-hardest`. `model router status` shows the counts,
`model router off` stops routing. The installer never edits your `settings.json`.

Requirements: macOS, Linux or Windows (with PowerShell 7, which Copilot CLI uses for hooks there), Python 3.8+
(standard library only), GitHub Copilot CLI or VS Code with Copilot, and a sizing backend: a TypeSafe API key in
`TYPESAFE_API_KEY`, or a Microsoft Decision-1 deployment in Azure AI Foundry (`MODEL_ROUTER_AZURE_ENDPOINT` and
`MODEL_ROUTER_AZURE_DEPLOYMENT`, Entra token via `az login`). Each value may live in the environment, the macOS Keychain or the
Windows Credential Manager.

## Pick your models

Defaults: Claude Haiku 5.5 (tiny), Sonnet 5.5 (everyday), Opus 5.5 (large), Opus 5.5 at high effort (hardest).
Change any size at any time, also after installing:

```bash
python3 -I ~/.copilot/model-router/router_copilot.py model large gpt-6.1-sol
python3 -I ~/.copilot/model-router/router_copilot.py model reset
```

or `model router model large gpt-6.1-sol` in chat. The next session uses it. `models` lists the models your account
can use, grouped by the size they fit (GitHub's own lightweight / versatile / powerful categories), so you can pick.

Renamed from `jev-router` on 2026-11-04, when the Azure Decision-1 backend made the name wrong. Old URLs redirect; an
old install migrates on the next `./install.sh`; old environment names and chat phrases keep working for one release.

## Documentation

- [`model-router-copilot/README.md`](model-router-copilot/README.md): install, uninstall, control phrases, how it works,
  models, optional fallbacks (`routercp` wrapper, MCP tool, status line), limits, privacy, testing.
- [`model-router-copilot/SECURITY.md`](model-router-copilot/SECURITY.md): what leaves the machine and when.
- Design notes, in reading order: [`01-analysis.md`](01-analysis.md) (the original router),
  [`02-copilot-capabilities.md`](02-copilot-capabilities.md) (what Copilot's hooks and agents can do),
  [`03-plan-copilot-cli.md`](03-plan-copilot-cli.md), [`04-plan-copilot-vscode.md`](04-plan-copilot-vscode.md),
  [`PROJECT-NOTES.md`](PROJECT-NOTES.md) (status log of the port).
- [`spikes/`](spikes/): the experiments that settled the open questions, with their evidence. Live end-to-end runs
  passed in Copilot CLI 1.0.105 and VS Code 1.144 (all four sizes), and for a changed per-size model.

## Status

Built and live-tested on macOS: the hook (Tier 1), the `routercp` wrapper, per-size model configuration. Built and
offline-tested only: the MCP fallback (Tier 2), the status line, and Windows support (PowerShell installer, `routercp.ps1`,
Credential Manager key, hook `powershell` entry). The Azure Decision-1 backend answered all four sizes in a live shell
test, not yet inside a Copilot session. Not built: a VS Code companion extension.
80 offline unit tests run in CI on Ubuntu, macOS and Windows.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security policy:
[SECURITY.md](SECURITY.md). Licensed under the [MIT License](LICENSE).
