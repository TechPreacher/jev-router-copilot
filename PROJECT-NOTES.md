# Project notes: porting model-router to GitHub Copilot

Working notes from the port, kept as history. The tool itself lives in [`model-router-copilot/`](model-router-copilot/README.md).
Before publishing (2026-11-02) the superseded `drafts/` folder and the raw Copilot session captures and debug logs under
`spikes/*-raw/` were removed; the spike write-ups in `spikes/*.md` keep the evidence they quoted.

Prepared 2026-10-29. Covers the analysis of `TechPreacher/model-router` (read-only, unchanged) and a port plan for Copilot CLI 1.0.88 and VS Code 1.144.

## Executive summary

model-router is a 369-line, stdlib-only Claude Code add-on. A `UserPromptSubmit` hook sends each message (first 6000 chars) to TypeSafe Jev, which sizes the job as tiny, everyday, large or hardest. The hook then injects an `additionalContext` note telling the main model to delegate to one of four subagents pinned to Haiku 5.5, Sonnet 5.5, Opus 5.5 or Fable 5.1. The design is fail-open, keeps secrets and short follow-ups local, and uses `decision: block` for in-chat `model router on/off/status`.

**The Copilot port is feasible except for the one feature everything depends on.** In both Copilot CLI and VS Code's Copilot harness, command-hook output on `userPromptSubmitted` is officially **dropped**, so there is no direct `additionalContext` and no blocking. The best candidate is the newer **`userPromptTransformed`** hook. Its `modifiedTransformedPrompt` can append the routing note to the model-facing prompt, but whether command hooks are honored for this event is not explicitly documented. **Spike S1 (run 2026-10-29) PASSED: see `spikes/S1-result.md`. Both `userPromptSubmitted.additionalContext` and `userPromptTransformed.modifiedTransformedPrompt` are honoured by CLI 1.0.88, contrary to the docs.**

Everything else maps cleanly:
- Custom agents in `~/.copilot/agents/*.agent.md` take a `model:` field, plus `model-policy: required`. Delegation goes through the native `task` tool.
- Copilot carries three of the four target Claude models. S3 (2026-10-29, CLI 1.0.105) verified `claude-haiku-5.5`, `claude-sonnet-5.5` and `claude-opus-5.5` via `--model`. `claude-fable-5.1` is a valid ID but **not available on this account** (absent from the model catalog), so `hardest` pins to Opus 5.5 until Fable is entitled. See `spikes/S3-result.md`.
- The hook config is a standalone file, so no settings.json merge is needed.
- `router.py` can be reused **verbatim** as a module behind a ~140-line adapter. A draft adapter passed an offline smoke test against a fake Jev server.

Because VS Code's Copilot harness reads the same `~/.copilot/hooks` and `~/.copilot/agents`, **one installer covers both the CLI and VS Code**. VS Code's **Claude harness** may run the existing model-router unchanged; S5 could not test it without the GUI (manual probe in `spikes/S5-result.md`).

If S1 fails, the fallback uses documented features only: a `sessionStart` standing instruction plus a `route_size` MCP tool. It is less reliable because the model chooses whether to call the tool.

Before investing, benchmark against Copilot's built-in **`--model auto` / `autoTier`** router. Unlike model-router, it switches the *main* model.

## Key gaps

| model-router piece | Copilot CLI | VS Code (Copilot harness) | VS Code (Local, legacy) | Best workaround |
|---|---|---|---|---|
| Per-prompt context injection | **Yes** (S1 verified on 1.0.88): `userPromptSubmitted.additionalContext` works despite docs; `userPromptTransformed` rewrite also works | **Yes** (S6): hooks fire, `userPromptTransformed` rewrite reaches the model; `additionalContext` **dropped** | **No** (`UserPromptSubmit` = common output only) | `userPromptTransformed` rewrite; else `sessionStart` context + `route_size` tool |
| Block prompt (in-chat on/off/status) | **No** | **No** | `continue:false` (unverified) | Rewrite the prompt to "echo this status"; `/model-router` skill; shell command; VS Code companion-extension commands |
| UI notice (`systemMessage`) | **No** | **No** | Yes | `statusLine` command (CLI); status bar item (extension) |
| Model-pinned helpers | Yes (`model`, `model-policy`, `/subagents`) | Yes (`model` string/array) | Yes (+ `runSubagent(model)`) | - |
| `transcript_path` for follow-up detection | **No** | **No** | n/a | Track seen `sessionId`s in `state.json` |
| Switch main model per message | No (only `--model`/`/model`) | No | No | `routercp` wrapper: size, then `copilot --model X -p` |
| Installer | Simpler (drop-in hook file) | Same files | Profile storage / settings | One `install.sh` for `~/.copilot` |
| API key in GUI-launched app | n/a | Needs the Keychain (already supported) | Same | Keep the Keychain fallback |

## Files

| File | Content |
|---|---|
| `01-analysis.md` | Repo analysis: data flow, hook contract, privacy logic, state, install mechanics, 15 fragile or notable points (e.g. SECURITY.md is stale after the Keychain commit; tiny-job delegation overhead; broad follow-up heuristic) |
| `02-copilot-capabilities.md` | What CLI and VS Code support, with source URLs, verified/unverified marks, model-ID table and capability matrix |
| `03-plan-copilot-cli.md` | CLI port: tiered architecture, piece mapping, layout, reuse table, config snippets, tests, phases, risks |
| `04-plan-copilot-vscode.md` | VS Code: per-harness paths A (Claude, zero-port), B (Copilot, shared with CLI), C (Local fallback), D (companion extension), tests, phases |
| `drafts/install.sh`, `drafts/uninstall.sh` | Bash installer and uninstaller for `${COPILOT_HOME:-~/.copilot}` (syntax-checked, not run) |
| `drafts/copilot-home/model-router/router_copilot.py` | Adapter (`transform`, `session-start`, `on/off/status/reset`) importing the unchanged `router.py`. Smoke-tested offline: OFF, control phrase, large route, follow-up, secret, idempotency, bad JSON |
| `drafts/copilot-home/hooks/*.json.tmpl` | Tier 1 (`userPromptTransformed`) and Tier 2 (`sessionStart`) hook files |
| `drafts/copilot-home/agents/router-*.agent.md` | Four helpers with cross-harness `model:` arrays |
| `drafts/copilot-home/skills/model-router/SKILL.md` | `/model-router on/off/status/reset` |
| `spikes/S1-result.md` | S1 spike evidence: payload keys, log lines, verdict, plan consequences |
| `spikes/S3-result.md` | S3 spike: verified model IDs, full catalog, Fable unavailable, plan consequences |
| `spikes/S4-result.md` | S4 spike: hook timeout, non-zero exit and bad JSON are all fail-open and silent; adapter rules |
| `spikes/S5-result.md` | S5 spike: UNVERIFIED (GUI-only harness picker); docs evidence and a manual probe procedure |
| `spikes/S6-result.md` | S6 spike: PASS. VS Code Copilot harness fires both prompt hooks, transform rewrite reaches the model, additionalContext dropped |
| `model-router-copilot/` | Phase 1 and Phase 3: installer, adapter, verbatim router.py, four agents, skill, Tier 2 MCP server (`router_mcp.py`), Tier 3 `bin/routercp`, status line, per-size model configuration (`models.json`, `model` command and chat phrase, agent templates), README, SECURITY, 50 unit tests |
| `spikes/E2E-cli-result.md` | Live CLI run on the real ~/.copilot: all sizes routed; nested-hook fix; reasoningEffort ignored |

Phase 1 and Phase 3 are built in `model-router-copilot/` (see status below). Not built: the VS Code companion extension (Path D).

## Phase 1 status (2026-10-30)

`model-router-copilot/` is built and verified offline: `router.py` is a byte-identical copy of the original, the adapter
`files/router_copilot.py` hooks `userPromptTransformed` only, four agents are pinned to Haiku 5.5 / Sonnet 5.5 / Opus 5.5 /
Opus 5.5 (`reasoningEffort: high`), and `install.sh` / `uninstall.sh` round-trip cleanly in a temporary `COPILOT_HOME`.
`bash tests/run.sh` runs 17 unittest cases against a fake Jev server (OFF, control phrases, `/` and `!`, secrets,
follow-ups, low confidence, every size, timeout, HTTP 500, invalid stdin, idempotency, agent/size consistency, bounded
session set): all pass. Live CLI end-to-end on the real `~/.copilot` passed on 2026-10-30 (all four sizes, see `spikes/E2E-cli-result.md`); it
exposed and fixed a nested-hook recursion risk, and showed that `reasoningEffort` in agent files is ignored. The router is
installed and OFF. Live VS Code end-to-end (Copilot harness, `code chat -r -m agent`) also passed on 2026-10-30: all four sizes, note
injected via `modifiedTransformedPrompt`, nested hook silent, each `code chat` send opened a new session (see
`spikes/E2E-vscode-result.md`). A Dock-launch (LaunchServices) re-run of prompt 1 also passed: VS Code resolves the login-shell PATH
itself, so the bare `python3` in the hook is found. The output folder is a git repository since 2026-11-02 (`main`, GitButler-managed).

Observation from this session: the original router sized the three-word message "Start Phase 1" as TINY (p=0.96) because
Jev sees the message without conversation context. Short imperative follow-ups that reference prior context are a known
weak spot (see `01-analysis.md`, follow-up heuristic). The Copilot adapter inherits this.

## Phase 3 status (2026-10-30, routercp live-tested 2026-11-02)

Built in `model-router-copilot/`, all optional and none installed by default:

- **Tier 2** `files/router_mcp.py`: stdlib stdio MCP server, one tool `route_size`, JSON-RPC 2.0 (initialize, ping,
  tools/list, tools/call; -32601 for unknown methods). Installed with `install.sh --tier2`, together with the
  `sessionStart` hook `hooks/model-router-session.json` (`router_copilot.py session` returns the standing rule). The
  `mcpServers` entry is printed, not written.
- **Tier 3** `files/bin/routercp`: sizes the prompt (`router_copilot.py size`), then runs `copilot --model <id>
  [--reasoning-effort medium|high] -p`. Sets `MODEL_ROUTER_PRESIZED=1` so the Tier 1 hook does not size twice.
  Installed to `model-router/bin/routercp`; PATH is the user's choice.
- **Status line** `files/router_statusline.py`: one line from `state.json` and the last `decisions.log` entry. Copied
  to the install dir; the `statusLine` snippet is printed, not written.

Verified offline: `bash tests/run.sh` passes 41 of 41 (18 existing, 23 in `tests/test_phase3.py`). The tests run the MCP
server over a pipe, the `size` mode for each route and OFF, `routercp` with a stub `copilot` on PATH (argv and env are
recorded, the real CLI never runs), the status line for OFF, no log, a sized line, a kept line, invalid stdin and a corrupt
log, and an installer round-trip in a temporary `COPILOT_HOME` (install, `--tier2`, re-run, uninstall: only the
pre-existing `settings.json` is left, unchanged). The real `~/.copilot` was never touched by Phase 3.

Not verified live: no `copilot` run with Tier 2 (the MCP `type: "local"` value was checked with
`copilot mcp add` into a temporary `COPILOT_HOME`, not by a model turn), no `routercp` run against the real CLI, the
`statusLine` layout in the CLI UI, and the `sessionStart` `additionalContext` consumption. The status line's
startup cost on this Mac is about 0.27 s, the same as a bare `python3 -I`, so the 50 ms target is not met by the
interpreter itself.

Live on 2026-11-02 (`spikes/ROUTERCP-live-result.md`): Tier 1 reinstall into the real `~/.copilot` was clean (one `.bak`,
stats kept, settings/mcp-config untouched) and `routercp` ran one everyday prompt on `claude-sonnet-5.5` as the main model;
the hook saw `MODEL_ROUTER_PRESIZED` and injected nothing (hook.end has no `output` key), no subagent, one decisions.log
line. Not live-tested: Tier 2, the status line inside a CLI session, `routercp -i`. Router is installed and OFF.

## Per-size model configuration (2026-11-02, live-tested same day)

Users can now pick the Copilot model per size, also on an installed copy: `router_copilot.py model <size> <model-id>
[--label "Name"] [--effort low|medium|high|none] [--policy required|preferred]`, or `model router model ...` in chat, or
`/model-router model ...`. Choices live in `~/.copilot/model-router/models.json` (never overwritten by a re-install); the
four agent files are rendered from templates installed in `model-router/agents/`, so a change re-renders the affected
agent file in place without the checkout. Labels flow into the routing note, status text and the helper footer; the
model ID, effort and policy into the agent file and `routercp`. Validation is local (ID shape, enumerations); entitlement
is only known to the CLI at run time, so `models` lists `copilot help config` IDs as a hint. Offline-tested: 50 tests
incl. an install-then-change-then-reinstall round trip in a temp `COPILOT_HOME`. Live-tested 2026-11-02
(`spikes/MODEL-live-result.md`): after a reinstall into the real `~/.copilot`, `model tiny claude-sonnet-5.5 --label
"Sonnet Tiny Test"` made the next CLI session run `router-tiny` on `claude-sonnet-5.5` with the test label in the footer;
`model reset` restored the defaults. Not live-tested: `--effort`, `--policy preferred`, an unentitled model ID.

Added 2026-11-02: `models` (and `model router models`) lists the models the account can use grouped by the size they
fit, alphabetical per group, from GitHub's model-picker categories in the catalog line that Copilot CLI logs at
`"logLevel": "all"` (`lightweight`/`versatile`/`powerful` -> tiny/everyday/large; hardest = powerful with a high
reasoning effort). Falls back to the flat `copilot help config` ID list with a hint when no log holds a catalog.
54 tests.

## Windows support (2026-11-03, offline-tested only)

The same install now works from PowerShell on Windows: `install.ps1` / `uninstall.ps1` are twins of the bash scripts
(same files, same self-test, same snippets), `routercp.ps1` twins `routercp`, and `tests/run.ps1` twins `run.sh`. The hook
templates carry a `powershell` entry next to `bash` (Copilot picks by OS; Windows needs PowerShell 7 on PATH), and a
new `@PY@` placeholder holds the interpreter command: a bare `python3` from `install.sh`, the full interpreter path
from `install.ps1` (first of `python`, `python3`, `py -3` that works). `router.py` stays verbatim: `files/router_compat.py`,
loaded by the adapter before the core, registers an `fcntl` stand-in on Windows (`msvcrt.locking` on the same lock
file), reads `TYPESAFE_API_KEY` from the Windows Credential Manager (`CredReadW`, generic credential) into the process
environment, and switches stdio to UTF-8 so a prompt with accents survives the console code page. `router_copilot.py key`
reports where the key was found. CI gained a `windows-latest` job; `.gitattributes` forces LF. 69 tests: `test_pwsh.py`
(installer, uninstaller, routercp.ps1, parse check; runs on all three runners) and `test_compat.py` (UTF-8, key mode;
on Windows the lock shim against a second process and a cmdkey round trip). Not done: a live Copilot session on
Windows, and which shell Copilot uses for `statusLine` there.

## Azure Decision-1 backend (2026-11-04, live-tested from a shell the same day)

`router.py` (upstream, copied verbatim) can now size with a Microsoft-Decision-1 deployment in Azure AI Foundry instead
of TypeSafe's hosted Jev: same request and answer shape, URL `<endpoint>/providers/microsoft/v1/systemone`, `model` =
deployment name. Active when `MODEL_ROUTER_AZURE_ENDPOINT` and `MODEL_ROUTER_AZURE_DEPLOYMENT` resolve (environment, then Keychain /
Credential Manager; both treated as secrets, never printed). Auth: `api-key` header from `MODEL_ROUTER_AZURE_API_KEY`, else an
Entra bearer token from `az account get-access-token --scope https://ai.azure.com/.default`. `az` takes ~2.5 s against
a 3 s hook, so the hook only reads a cached token (`azure-token.json`, mode 600) and, when it is missing or within ten
minutes of expiry, spawns `router.py azure-token` detached and lets the message through unrouted once; `on` (shell),
`size` and `routercp` wait for the token. `key` reports the backend and each value's source. 80 tests; `test_azure.py`
uses the fake server as a Foundry deployment and a stub `az` on PATH. Live-tested the same day with the core's hook
from a shell against a real GlobalStandard deployment (`spikes/AZURE-live-result.md`): all four canned prompts answered
in 420 to 500 ms, tiny/large/hardest routed, everyday kept at p=0.56 (under the 0.60 threshold). First attempts were
401 PermissionDenied until the user got `Cognitive Services User` on the resource (Owner on the subscription is control
plane only; local auth was disabled). Not done: a Copilot session with the Azure backend. The Claude Code side
(upstream) has no test suite, so its path is covered through this port's tests only.

## Renamed to model-router (2026-11-04)

With a second backend the product name no longer belongs to Jev. Everything backend-neutral was renamed in both
repos in one cut (see "Renamed from jev-router" in the package README for the full list); `TYPESAFE_API_KEY`, the
TypeSafe backend wording and `tests/fake_jev.py` stay. The core reads the old environment and Keychain names and the
old state key for one release, the adapter accepts `jev router ...` and bare `router ...` phrases and ignores old
`[jev-router]` notes in replayed history, and both installers migrate a `jev-router` install in place. The repos are
renamed on GitHub (`TechPreacher/model-router`, `TechPreacher/model-router-copilot`); old URLs redirect. The design
notes `01`-`04` and `spikes/` keep the old names as history. Live check after migrating the real `~/.copilot`: one tiny
prompt in Copilot CLI (session 3e9c94d8, 5.89 credits, 24 s) carried the `[model-router] Sized as TINY (p=1.00)` note,
`subagent.started` named `router-tiny` on `claude-haiku-5.5`, and the reply ended with the `(router-tiny)` footer.

## Next step

S1, S3 and S4 done (all pass). S5 is UNVERIFIED: the Claude harness can only be selected in the GUI, so `spikes/S5-result.md` gives a 2-minute manual probe. S6 PASSED: both hooks fire in the VS Code Copilot harness with CLI-identical payloads, `additionalContext` is dropped there (unlike the CLI), and the `userPromptTransformed` rewrite reached the model (reply ended with the injected word, `spikes/S6-result.md`). **Path B (one `~/.copilot` install for CLI and VS Code) is confirmed** and proven end-to-end in both the CLI and the VS Code Copilot harness (`spikes/E2E-cli-result.md`, `spikes/E2E-vscode-result.md`). Only S5 (VS Code Claude harness) remains a manual probe.
