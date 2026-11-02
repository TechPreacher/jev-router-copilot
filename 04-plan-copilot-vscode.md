# 04 - Plan: jev-router for GitHub Copilot in VS Code

Target: VS Code 1.144 (installed locally) with GitHub Copilot. Capabilities and sources are in `02-copilot-capabilities.md`.

## 1. First decide the harness

VS Code agent sessions now run in one of four **harnesses**: Local, Copilot, Claude or Codex. You pick one per session in **Session Target**, before the first prompt. Hooks, agent locations and subagent tools all depend on that choice, so the plan has one path per harness:

| Path | Harness | Effort | Fidelity | Key unknown |
|---|---|---|---|---|
| **A - Zero-port** | Claude | ~0 (existing install) | Full, if VS Code honors Claude Code hooks | Does the Claude harness run `~/.claude/settings.json` `UserPromptSubmit` hooks and their `additionalContext` / `decision: block` / `systemMessage`? (S5) |
| **B - Shared with CLI** | Copilot (recommended default) | ~0 beyond the CLI port | Same as CLI Tier 1 | Does `userPromptTransformed` fire and get honored in the VS Code Copilot harness? (S6) |
| **C - Legacy** | Local | Medium | Lower (model-mediated) | No per-prompt injection exists. Uses `SessionStart` context plus a sizing tool |
| **D - Extension** | Any (UX add-on) | Medium | Toggle/stats UI only | Cannot intercept built-in chat prompts |

Recommendation: run spikes S5 and S6 first. If S6 passes, **B is the product**: one install into `~/.copilot` serves both the CLI and VS Code. A is a bonus for users who choose the Claude harness. C is only needed for users stuck on the Local harness. D is optional polish.

## 2. Mapping each jev-router piece (Copilot harness = Path B)

| Piece | VS Code Copilot harness | Status |
|---|---|---|
| (a) Interception + sizing | Same `~/.copilot/hooks/jev-router.json` -> `jev_copilot.py transform` as the CLI. VS Code reads `~/.copilot/hooks/` (documented) | **S6: both events fire, CLI-identical camelCase payloads** |
| (b) Inject note | `modifiedTransformedPrompt`. `userPromptSubmitted` command output is ignored (documented, **confirmed by S6**: additionalContext dropped in VS Code although the CLI honours it) | **S6 PASS**: rewrite reached the model (`spikes/S6-result.md`) |
| (b') UI line | None. Optional: a status bar item from Path D | - |
| (c) Helpers | Same `~/.copilot/agents/jev-*.agent.md` (VS Code reads `~/.copilot/agents`), delegated via the native `task` tool. Set `model` as an **array** so one file works across harnesses: `model: ['claude-opus-5.5', 'Claude Opus 5.5 (copilot)']` ("first available model" wins) | Array semantics documented; whether an unknown entry is skipped silently is **unverified** |
| (d) Toggle/stats | Same control phrases (rewrite-to-echo) or the `/jev-router` skill; shared `~/.copilot/jev-router/state.json` across CLI and VS Code | S6 PASS; shared state confirmed by the VS Code e2e (same `decisions.log`) |
| (e) Installer | **The CLI installer covers it.** Add a README note: select the Copilot harness; hooks are Preview; hooks may need a trusted workspace | - |
| (f) Privacy | Same `decide()` | Reuse |
| API key | VS Code launched from the Dock has no shell env, so the **Keychain fallback is required**, just like the Claude desktop app. `router.py` already has it | Reuse |

Note: `.github/hooks/*.json` in a repo also loads, but only for that workspace. Keep jev-router user-level.

## 3. Path A - Claude harness (zero-port)

The Claude harness runs the Anthropic Claude Agent SDK inside VS Code, billed through Copilot or your own key. VS Code release notes say it reads Claude configuration (agents, skills, hooks in `~/.claude/settings.json`). If that holds at runtime, the existing jev-router works unchanged: same hook, same `~/.claude/agents/jev-*.md`, same `model: haiku|sonnet|opus|fable` aliases.

Spike **S5** (2026-10-29: UNVERIFIED, see `spikes/S5-result.md`; harness picker is GUI-only, `code chat` has no harness flag, docs say the Claude harness has its own hook implementation and do not list `~/.claude/settings.json`):
1. Open a Claude-harness session.
2. Type `jev router status`. Expect a blocked prompt with the status text.
3. Type `jev router on`, then a medium task. Expect `Jev → everyday` and delegation to `jev-everyday`.
4. Check `~/.claude/jev-router/decisions.log`.

If it works, add one paragraph to the original repo's README (later, outside this task). The model mapping uses Claude aliases, and the harness picker lists Claude models under both Anthropic and Copilot.

## 4. Path C - Local harness (legacy) fallback

Constraints (documented): `UserPromptSubmit` supports only `continue` / `stopReason` / `systemMessage`, with no `additionalContext`. `SessionStart` supports `hookSpecificOutput.additionalContext`. Subagents run through `runSubagent`, which takes an **explicit `model` parameter** (highest precedence). Prompt files and `handoffs` are Local-only.

Design:
1. **`SessionStart` hook** -> `jev_copilot.py vscode-session-start` returns a standing instruction: "Before working on any new user request (not a short follow-up), call the `jev_size` tool with the user's message. If it returns a size, call `runSubagent` with agent `jev-<size>` and the given model; relay the result as-is."
2. **Sizing tool**: the same `jev_mcp.py` stdio MCP server as CLI Tier 2, registered in the VS Code user MCP configuration. Alternatively, the Path D extension registers it as a language model tool (`vscode.lm.registerTool`).
3. **`UserPromptSubmit` hook** (optional) -> handles only the control phrases: run the action and return `{"continue": false, "stopReason": "<status text>"}`. Whether `continue:false` stops the turn for this event is **unverified (S7)**. Otherwise rely on the skill/command.
4. **Agents**: the same `.agent.md` files with the qualified-name entry in the `model` array. Local reads user agents from VS Code profile storage or `chat.agentFilesLocations`. Add `~/.copilot/agents` there, or ship them as an agent plugin.
5. Requires `chat.useHooks` and a trusted workspace.

Weakness: routing depends on the model choosing to call `jev_size` every turn. Expect misses on long sessions. Measure compliance in `decisions.log` against the prompt count.

## 5. Path D - VS Code extension (optional UX, not a router)

There is no API that lets an extension rewrite or annotate prompts sent to the built-in agent. The chat participant guide is marked **deprecated**, and a `@jev` participant would lose the agent tool loop. So the extension is only a companion:
- **Status bar item:** "Jev: ON · large 83%". It watches `~/.copilot/jev-router/decisions.log` and fills the gap left by the missing `systemMessage`.
- **Commands:** `Jev Router: Turn On / Turn Off / Show Status / Reset Stats`. They run `jev_copilot.py on|off|status|reset`. This gives a clean toggle with no chat round-trip.
- **Optional `jev_size` LM tool** for Path C, instead of MCP.
- **Command:** `Jev Router: Set TypeSafe Key` stores the key in VS Code SecretStorage and also writes it to the macOS Keychain via `security add-generic-password -U`.
- Possible later use: the Language Model API (`vscode.lm.selectChatModels({vendor:'copilot', family:...})`) to run a whole job on a sized model inside the extension's own command, for example "Jev: Run selection on best-sized model". That is a different product, not a router.

## 6. Proposed layout additions (on top of the CLI project)

```
jev-router-copilot/
  files/
    jev_copilot.py            # + vscode-session-start, + control-phrase continue:false mode
    jev_mcp.py                # shared Tier 2 / Path C sizing tool
  vscode/
    README.md                 # harness guidance, settings (chat.useHooks, workspace trust), Keychain
    mcp.user.json.example     # snippet for the VS Code user MCP config (Path C)
    local-hooks.json.example  # Local-harness SessionStart + UserPromptSubmit entries
  vscode-extension/           # Path D (optional): package.json, src/extension.ts
```

The agent files are shared. Use `model:` arrays so they serve the CLI, the VS Code Copilot harness and VS Code Local.

## 7. Testing approach

- **S5** (Claude harness), **S6** (Copilot harness + `userPromptTransformed` BANANA test, same as CLI S1), **S7** (Local `continue:false` on `UserPromptSubmit`), **S8** (model array with mixed ID styles: does the agent start, and on which model? Check the chat debug view or the subagent credit display via `chat.subagents.showCreditUsage`).
- Reuse the CLI unit tests. Add fixtures for VS Code snake_case payloads (`hook_event_name`, `session_id`).
- Manual end-to-end per harness with the same four canned prompts. Assert `decisions.log` routes and the `— done by` footers. **Copilot harness: PASS 2026-10-30** (`spikes/E2E-vscode-result.md`); Claude harness: not run (S5 manual probe).
- Extension (if built): `@vscode/test-electron` smoke test for the commands and the status bar parsing.

## 8. Phased task list

| Phase | Tasks | Exit criterion |
|---|---|---|
| 0 Spikes | S5, S6, S7, S8 | Pick the supported harness(es) |
| 1 Path B | Nothing new if the CLI port is done; add VS Code notes, the agent `model` arrays and Keychain guidance | Routing works in a Copilot-harness session |
| 2 Path A | Document the Claude-harness usage of the original jev_router (if S5 passes) | Documented |
| 3 Path C | `vscode-session-start` mode, `jev_mcp.py` registration, Local hook examples | >= 80% of eligible prompts sized in a test session |
| 4 Path D | Companion extension: toggle, status bar, key setup | Marketplace-ready VSIX (optional) |
| 5 Evaluate | Compare against VS Code **Auto** model selection on cost and quality | Keep or drop |

## 9. Risks

- **Hooks are Preview in VS Code**, and the harness model is new in 2026, so the docs are moving. Re-run the spikes after each VS Code release.
- **Enterprise policy** can force the Copilot harness, disable Claude/Codex, and govern hooks via policy files.
- **Workspace trust:** hooks may not run in untrusted folders.
- **Data flow:** prompts go to api.typesafe.ai from inside a Copilot session. Check against your org's Copilot data policy, especially on the EMU work account.
