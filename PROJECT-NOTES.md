# Project notes: porting jev-router to GitHub Copilot

Working notes from the port, kept as history. The tool itself lives in [`jev-router-copilot/`](jev-router-copilot/README.md).
Before publishing (2026-11-02) the superseded `drafts/` folder and the raw Copilot session captures and debug logs under
`spikes/*-raw/` were removed; the spike write-ups in `spikes/*.md` keep the evidence they quoted.

Prepared 2026-10-29. Covers the analysis of `TechPreacher/jev_router` (read-only, unchanged) and a port plan for Copilot CLI 1.0.88 and VS Code 1.144.

## Executive summary

jev_router is a 369-line, stdlib-only Claude Code add-on. A `UserPromptSubmit` hook sends each message (first 6000 chars) to TypeSafe Jev, which sizes the job as tiny, everyday, large or hardest. The hook then injects an `additionalContext` note telling the main model to delegate to one of four subagents pinned to Haiku 5.5, Sonnet 5.5, Opus 5.5 or Fable 5.1. The design is fail-open, keeps secrets and short follow-ups local, and uses `decision: block` for in-chat `jev router on/off/status`.

**The Copilot port is feasible except for the one feature everything depends on.** In both Copilot CLI and VS Code's Copilot harness, command-hook output on `userPromptSubmitted` is officially **dropped**, so there is no direct `additionalContext` and no blocking. The best candidate is the newer **`userPromptTransformed`** hook. Its `modifiedTransformedPrompt` can append the routing note to the model-facing prompt, but whether command hooks are honored for this event is not explicitly documented. **Spike S1 (run 2026-10-29) PASSED: see `spikes/S1-result.md`. Both `userPromptSubmitted.additionalContext` and `userPromptTransformed.modifiedTransformedPrompt` are honoured by CLI 1.0.88, contrary to the docs.**

Everything else maps cleanly:
- Custom agents in `~/.copilot/agents/*.agent.md` take a `model:` field, plus `model-policy: required`. Delegation goes through the native `task` tool.
- Copilot carries three of the four target Claude models. S3 (2026-10-29, CLI 1.0.105) verified `claude-haiku-5.5`, `claude-sonnet-5.5` and `claude-opus-5.5` via `--model`. `claude-fable-5.1` is a valid ID but **not available on this account** (absent from the model catalog), so `hardest` pins to Opus 5.5 until Fable is entitled. See `spikes/S3-result.md`.
- The hook config is a standalone file, so no settings.json merge is needed.
- `router.py` can be reused **verbatim** as a module behind a ~140-line adapter. A draft adapter passed an offline smoke test against a fake Jev server.

Because VS Code's Copilot harness reads the same `~/.copilot/hooks` and `~/.copilot/agents`, **one installer covers both the CLI and VS Code**. VS Code's **Claude harness** may run the existing jev_router unchanged; S5 could not test it without the GUI (manual probe in `spikes/S5-result.md`).

If S1 fails, the fallback uses documented features only: a `sessionStart` standing instruction plus a `jev_size` MCP tool. It is less reliable because the model chooses whether to call the tool.

Before investing, benchmark against Copilot's built-in **`--model auto` / `autoTier`** router. Unlike jev_router, it switches the *main* model.

## Key gaps

| jev-router piece | Copilot CLI | VS Code (Copilot harness) | VS Code (Local, legacy) | Best workaround |
|---|---|---|---|---|
| Per-prompt context injection | **Yes** (S1 verified on 1.0.88): `userPromptSubmitted.additionalContext` works despite docs; `userPromptTransformed` rewrite also works | **Yes** (S6): hooks fire, `userPromptTransformed` rewrite reaches the model; `additionalContext` **dropped** | **No** (`UserPromptSubmit` = common output only) | `userPromptTransformed` rewrite; else `sessionStart` context + `jev_size` tool |
| Block prompt (in-chat on/off/status) | **No** | **No** | `continue:false` (unverified) | Rewrite the prompt to "echo this status"; `/jev-router` skill; shell command; VS Code companion-extension commands |
| UI notice (`systemMessage`) | **No** | **No** | Yes | `statusLine` command (CLI); status bar item (extension) |
| Model-pinned helpers | Yes (`model`, `model-policy`, `/subagents`) | Yes (`model` string/array) | Yes (+ `runSubagent(model)`) | - |
| `transcript_path` for follow-up detection | **No** | **No** | n/a | Track seen `sessionId`s in `state.json` |
| Switch main model per message | No (only `--model`/`/model`) | No | No | `jevcp` wrapper: size, then `copilot --model X -p` |
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
| `drafts/copilot-home/jev-router/jev_copilot.py` | Adapter (`transform`, `session-start`, `on/off/status/reset`) importing the unchanged `router.py`. Smoke-tested offline: OFF, control phrase, large route, follow-up, secret, idempotency, bad JSON |
| `drafts/copilot-home/hooks/*.json.tmpl` | Tier 1 (`userPromptTransformed`) and Tier 2 (`sessionStart`) hook files |
| `drafts/copilot-home/agents/jev-*.agent.md` | Four helpers with cross-harness `model:` arrays |
| `drafts/copilot-home/skills/jev-router/SKILL.md` | `/jev-router on/off/status/reset` |
| `spikes/S1-result.md` | S1 spike evidence: payload keys, log lines, verdict, plan consequences |
| `spikes/S3-result.md` | S3 spike: verified model IDs, full catalog, Fable unavailable, plan consequences |
| `spikes/S4-result.md` | S4 spike: hook timeout, non-zero exit and bad JSON are all fail-open and silent; adapter rules |
| `spikes/S5-result.md` | S5 spike: UNVERIFIED (GUI-only harness picker); docs evidence and a manual probe procedure |
| `spikes/S6-result.md` | S6 spike: PASS. VS Code Copilot harness fires both prompt hooks, transform rewrite reaches the model, additionalContext dropped |
| `jev-router-copilot/` | Phase 1 and Phase 3: installer, adapter, verbatim router.py, four agents, skill, Tier 2 MCP server (`jev_mcp.py`), Tier 3 `bin/jevcp`, status line, per-size model configuration (`models.json`, `model` command and chat phrase, agent templates), README, SECURITY, 50 unit tests |
| `spikes/E2E-cli-result.md` | Live CLI run on the real ~/.copilot: all sizes routed; nested-hook fix; reasoningEffort ignored |

Phase 1 and Phase 3 are built in `jev-router-copilot/` (see status below). Not built: the VS Code companion extension (Path D).

## Phase 1 status (2026-10-30)

`jev-router-copilot/` is built and verified offline: `router.py` is a byte-identical copy of the original, the adapter
`files/jev_copilot.py` hooks `userPromptTransformed` only, four agents are pinned to Haiku 5.5 / Sonnet 5.5 / Opus 5.5 /
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

## Phase 3 status (2026-10-30, jevcp live-tested 2026-11-02)

Built in `jev-router-copilot/`, all optional and none installed by default:

- **Tier 2** `files/jev_mcp.py`: stdlib stdio MCP server, one tool `jev_size`, JSON-RPC 2.0 (initialize, ping,
  tools/list, tools/call; -32601 for unknown methods). Installed with `install.sh --tier2`, together with the
  `sessionStart` hook `hooks/jev-router-session.json` (`jev_copilot.py session` returns the standing rule). The
  `mcpServers` entry is printed, not written.
- **Tier 3** `files/bin/jevcp`: sizes the prompt (`jev_copilot.py size`), then runs `copilot --model <id>
  [--reasoning-effort medium|high] -p`. Sets `JEV_ROUTER_PRESIZED=1` so the Tier 1 hook does not size twice.
  Installed to `jev-router/bin/jevcp`; PATH is the user's choice.
- **Status line** `files/jev_statusline.py`: one line from `state.json` and the last `decisions.log` entry. Copied
  to the install dir; the `statusLine` snippet is printed, not written.

Verified offline: `bash tests/run.sh` passes 41 of 41 (18 existing, 23 in `tests/test_phase3.py`). The tests run the MCP
server over a pipe, the `size` mode for each route and OFF, `jevcp` with a stub `copilot` on PATH (argv and env are
recorded, the real CLI never runs), the status line for OFF, no log, a sized line, a kept line, invalid stdin and a corrupt
log, and an installer round-trip in a temporary `COPILOT_HOME` (install, `--tier2`, re-run, uninstall: only the
pre-existing `settings.json` is left, unchanged). The real `~/.copilot` was never touched by Phase 3.

Not verified live: no `copilot` run with Tier 2 (the MCP `type: "local"` value was checked with
`copilot mcp add` into a temporary `COPILOT_HOME`, not by a model turn), no `jevcp` run against the real CLI, the
`statusLine` layout in the CLI UI, and the `sessionStart` `additionalContext` consumption. The status line's
startup cost on this Mac is about 0.27 s, the same as a bare `python3 -I`, so the 50 ms target is not met by the
interpreter itself.

Live on 2026-11-02 (`spikes/JEVCP-live-result.md`): Tier 1 reinstall into the real `~/.copilot` was clean (one `.bak`,
stats kept, settings/mcp-config untouched) and `jevcp` ran one everyday prompt on `claude-sonnet-5.5` as the main model;
the hook saw `JEV_ROUTER_PRESIZED` and injected nothing (hook.end has no `output` key), no subagent, one decisions.log
line. Not live-tested: Tier 2, the status line inside a CLI session, `jevcp -i`. Router is installed and OFF.

## Per-size model configuration (2026-11-02, live-tested same day)

Users can now pick the Copilot model per size, also on an installed copy: `jev_copilot.py model <size> <model-id>
[--label "Name"] [--effort low|medium|high|none] [--policy required|preferred]`, or `jev router model ...` in chat, or
`/jev-router model ...`. Choices live in `~/.copilot/jev-router/models.json` (never overwritten by a re-install); the
four agent files are rendered from templates installed in `jev-router/agents/`, so a change re-renders the affected
agent file in place without the checkout. Labels flow into the routing note, status text and the helper footer; the
model ID, effort and policy into the agent file and `jevcp`. Validation is local (ID shape, enumerations); entitlement
is only known to the CLI at run time, so `models` lists `copilot help config` IDs as a hint. Offline-tested: 50 tests
incl. an install-then-change-then-reinstall round trip in a temp `COPILOT_HOME`. Live-tested 2026-11-02
(`spikes/MODEL-live-result.md`): after a reinstall into the real `~/.copilot`, `model tiny claude-sonnet-5.5 --label
"Sonnet Tiny Test"` made the next CLI session run `jev-tiny` on `claude-sonnet-5.5` with the test label in the footer;
`model reset` restored the defaults. Not live-tested: `--effort`, `--policy preferred`, an unentitled model ID.

Added 2026-11-02: `models` (and `jev router models`) lists the models the account can use grouped by the size they
fit, alphabetical per group, from GitHub's model-picker categories in the catalog line that Copilot CLI logs at
`"logLevel": "all"` (`lightweight`/`versatile`/`powerful` -> tiny/everyday/large; hardest = powerful with a high
reasoning effort). Falls back to the flat `copilot help config` ID list with a hint when no log holds a catalog.
54 tests.

## Next step

S1, S3 and S4 done (all pass). S5 is UNVERIFIED: the Claude harness can only be selected in the GUI, so `spikes/S5-result.md` gives a 2-minute manual probe. S6 PASSED: both hooks fire in the VS Code Copilot harness with CLI-identical payloads, `additionalContext` is dropped there (unlike the CLI), and the `userPromptTransformed` rewrite reached the model (reply ended with the injected word, `spikes/S6-result.md`). **Path B (one `~/.copilot` install for CLI and VS Code) is confirmed** and proven end-to-end in both the CLI and the VS Code Copilot harness (`spikes/E2E-cli-result.md`, `spikes/E2E-vscode-result.md`). Only S5 (VS Code Claude harness) remains a manual probe.
