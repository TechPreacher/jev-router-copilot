# 03 - Plan: jev-router for GitHub Copilot CLI

Target: Copilot CLI (`copilot`, tested locally at 1.0.88). Capabilities and sources: see `02-copilot-capabilities.md`.

## 1. The core problem

Claude Code's router depends on a `UserPromptSubmit` hook that can **add context** and **block** a prompt. In the Copilot CLI, command hooks on `userPromptSubmitted` run but their **output is dropped** (documented). So the plan uses a different hook and keeps documented-only fallbacks ready.

## 2. Mapping each jev-router piece

| Piece | Claude Code | Copilot CLI equivalent | Status |
|---|---|---|---|
| (a) Prompt interception + Jev sizing | `UserPromptSubmit` command hook -> `router.py hook` | `userPromptTransformed` command hook in `~/.copilot/hooks/jev-router.json` -> `jev_copilot.py transform`. Sizing uses the input `prompt`; `decide()` from `router.py` is reused unchanged | Hook fires: documented. Command output honored: **verified by S1 on 1.0.88** (both `userPromptSubmitted.additionalContext` and `userPromptTransformed` rewrite); see `spikes/S1-result.md`. S6: VS Code drops `additionalContext`, so emit on `userPromptTransformed` only |
| (b) Inject routing note | `additionalContext` | Output `{"modifiedTransformedPrompt": transformedPrompt + "\n\n[jev-router] ..."}`. The note is appended to model-facing content; the user's timeline is unchanged; it is stored in session history and replayed on resume | Depends on S1 |
| (b') UI line `Jev → large (83%)` | `systemMessage` | **No equivalent.** Workaround: `statusLine` command in `~/.copilot/settings.json` that prints the last decision from `decisions.log` (documented `statusLine.type: "command"`) | Documented; layout unverified |
| (c) Four model-pinned helpers | `~/.claude/agents/jev-*.md`, `model: haiku|sonnet|opus|fable` | `~/.copilot/agents/jev-*.agent.md`, `model: claude-haiku-5.5` etc. + `model-policy: required`; the main agent delegates through its `task` tool. Alternative pin: `subagents.agents.jev-tiny.model` in settings (`/subagents`) | Frontmatter documented; 5.5 IDs **verified by S3**; Fable unavailable, `hardest` -> `claude-opus-5.5` |
| (d) on/off/status in chat | Hook `decision: block` swallows the phrase | **No blocking.** The hook performs the action and rewrites the transformed prompt to "reply with exactly this status text" (one cheap model turn). Also: skill `/jev-router` that runs the CLI command, and the shell command `python3 ~/.copilot/jev-router/jev_copilot.py on|off|status|reset` | Depends on S1; skill path documented |
| (d') Stats | `~/.claude/jev-router/state.json`, `decisions.log` | Same code with `JEV_ROUTER_HOME=~/.copilot/jev-router` | Reuse |
| (e) Installer | Copies files + JSON merge into `settings.json` | Copies files + **drops a standalone hook file** `~/.copilot/hooks/jev-router.json` (no JSON merge needed; uninstall = delete). Alternative: package as a Copilot plugin (`copilot plugin install`) | Documented |
| (f) Privacy filters | `/`, `!`, follow-ups, secret regex, OFF | Same `decide()`; the `/` and `!` checks stay. Follow-up detection needs a new history signal because prompt hooks get no `transcript_path` (see 4.2) | Reuse + small adapter |
| API key | env, else macOS Keychain | Same; the CLI is started from a shell, so env normally works | Reuse |

## 3. Architecture (tiered, so a failed spike does not kill the project)

- **Tier 1 (primary): `userPromptTransformed` rewrite.** Closest to the original. Per-message, deterministic, no extra tool calls.
- **Tier 2 (fallback, uses documented features only): SessionStart instruction + `jev_size` tool.** A `sessionStart` hook returns `additionalContext` (documented as consumed for command hooks) with a standing rule: "For each new user request that is not a short follow-up, call the `jev_size` tool with the user's message, then delegate as it says." `jev_size` is a tiny stdlib-only MCP stdio server (`jev_mcp.py`, registered in `~/.copilot/mcp-config.json`) that wraps `decide()` + `record()` and returns the routing note. Downsides: the model decides whether to call it (less reliable), and it costs one tool round-trip on the main model per message.
- **Tier 3 (optional, true main-model routing): wrapper `jevcp`.** `jevcp "prompt"` sizes the prompt, then runs `copilot --model <id> -p "prompt"` (or `-i` for interactive). This routes the **main** model with no subagent overhead, which Claude Code cannot do. Limited to one-shot or session starts; whether `--continue --model X` switches model mid-conversation is **unverified**.
- **Not recommended: Copilot SDK REPL.** The SDK's programmatic `onUserPromptSubmitted` supports `additionalContext` and `decision: "block"` (full parity), but you would rebuild the terminal UI.

Also consider **Copilot's own `--model auto` + `autoTier`** (`efficiency|balance|intelligence|fast`). It is a built-in router that changes the main model, with no third-party data flow. Benchmark jev-router against it before investing (Phase 4).

## 4. Implementation details

### 4.1 Proposed layout (sibling project; the original repo stays untouched)

```
jev-router-copilot/
  README.md  SECURITY.md  LICENSE
  install.sh  uninstall.sh                 # bash, targets ${COPILOT_HOME:-~/.copilot}
  files/
    router.py                              # VERBATIM copy of jev_router/files/router.py (core)
    jev_copilot.py                         # Copilot adapter: transform | session-start | on|off|status|reset
    jev_mcp.py                             # Tier 2: stdio MCP server exposing jev_size (optional)
    hooks/jev-router.json.tmpl             # hook file template (@JR@ = install dir)
    agents/jev-tiny.agent.md ... jev-hardest.agent.md
    skills/jev-router/SKILL.md             # /jev-router on|off|status -> runs the CLI command
  bin/jevcp                                # Tier 3 wrapper (optional)
  tests/
    test_adapter.py                        # unittest, stdlib only
    fixtures/*.json                        # sample hook payloads (camelCase + snake_case)
    fake_jev.py                            # local HTTP server mimicking api.typesafe.ai
```

Early drafts of the adapter, hook file, agents and install/uninstall lived in `drafts/`; they were superseded by `jev-router-copilot/` and removed before publishing.

### 4.2 Reuse vs. adapt from `router.py`

| Function | Reuse? | Notes |
|---|---|---|
| `SIZES`, `QUESTION`, `ask_jev`, `get_key`, `decide`, `record`, `locked_state`, `read_state`, `status_text`, `set_enabled`, `SECRETS`, `is_followup` | **Verbatim** (import `router` as a module) | `JEV_ROUTER_HOME` env selects `~/.copilot/jev-router`. `router.URL` can be monkey-patched for tests |
| `hook()` | **Replace** with `transform()` | Different input (`sessionId`, `prompt`, `transformedPrompt`) and output (`modifiedTransformedPrompt`) |
| History signal | **New** | No `transcript_path` on prompt events. Track seen `sessionId`s in state (first prompt of a session = no history), pruned by age |
| Routing note text | **Adapt** | "Use the `task` tool to delegate to the custom agent `jev-large` (runs on Claude Opus 5.5) ..." |
| Control phrases | **Adapt** | Cannot block: handle the action, then rewrite the prompt so the model echoes the status |
| Idempotency | **New** | The event can fire for earlier queued messages; skip if `[jev-router]` is already in `transformedPrompt` |
| `settings_hook.py` | **Not needed** | A standalone hook file replaces the JSON merge |

Two small upstream refactors would help both projects (optional, for later): make `URL` and the note template overridable, and rename the main-model hint. They are not required, because the adapter imports the core unchanged.

### 4.3 Hook file (`~/.copilot/hooks/jev-router.json`)

```json
{
  "version": 1,
  "hooks": {
    "userPromptTransformed": [
      {
        "type": "command",
        "bash": "python3 -I \"/Users/<you>/.copilot/jev-router/jev_copilot.py\" transform",
        "timeoutSec": 3
      }
    ]
  }
}
```

The installer writes the absolute path, so it does not rely on `$HOME` expansion or `cwd`. Timeouts are fail-open (documented).

### 4.4 Agent file (`~/.copilot/agents/jev-large.agent.md`)

```markdown
---
name: jev-large
description: Jev router helper for large jobs (a multi-step build, research, a full report). Use only when a [jev-router] note in the conversation says to delegate to jev-large.
model: claude-opus-5.5
model-policy: required
include-custom-instructions: true
user-invocable: false
---
You are the large-size helper in a model router. ...
End your reply with exactly this final line and nothing after it:
— done by Claude Opus 5.5 (jev-large)
```

Notes:
- `user-invocable: false` hides the helpers from `/agent` but keeps them available as subagents. Without it they clutter the picker.
- `include-custom-instructions: true` matches Claude Code, where subagents see CLAUDE.md. In Copilot the default is false.
- If `model-policy: required` makes the agent fail hard when the model is unavailable, drop it and rely on the fallback sentence in the routing note (S2).

### 4.5 Install / uninstall (sketch; the real scripts are in `jev-router-copilot/`)

`install.sh`:
1. Check `python3`.
2. Set `CP="${COPILOT_HOME:-$HOME/.copilot}"` and `mkdir -p "$CP/jev-router" "$CP/agents" "$CP/hooks"`.
3. Copy `router.py`, `jev_copilot.py` and the README.
4. Copy the agents, backing up any changed file first (`cmp -s`).
5. Render `jev-router.json` from the template with `sed "s#@JR@#$CP/jev-router#g"`.
6. Create OFF state only if `state.json` is missing.
7. Warn when `TYPESAFE_API_KEY` is unset and no Keychain item exists.
8. Print "restart copilot, then type `jev router on`".

`uninstall.sh`: delete `$CP/hooks/jev-router.json`, the four `jev-*.agent.md` files and `$CP/jev-router`.

Plugin alternative: `plugin.json` + `agents/` + `hooks.json` + `skills/`. Then `copilot plugin install TechPreacher/jev-router-copilot` and `/plugins` can enable or disable the hooks (v1.0.76+). Open question: how the plugin's hook finds `router.py` inside the plugin directory (an environment variable for the plugin root is unverified). Keep the script installer as the primary path.

## 5. Testing approach

**Spikes (do first, about 1 hour total):**
- **S1 Injection:** a throwaway hook file on `userPromptTransformed` that dumps stdin to `/tmp/s1.json` and returns `{"modifiedTransformedPrompt": "<original>\n\nAlso end your answer with the word BANANA."}`. Pass if the reply ends with BANANA. Record the exact payload keys (camelCase vs snake_case, whether `transformedPrompt` is a string) and what happens on `--resume`. Repeat with `userPromptSubmitted` + `additionalContext` to confirm it is dropped.
- **S2 Agent pin:** `copilot -p "Use the jev-tiny agent to tell me which model you are"`. Confirm in `/tasks` or `~/.copilot/logs` that the subagent ran on Haiku. Then test with `model-policy: required` and a bogus model.
- **S3 Model IDs:** DONE (see `spikes/S3-result.md`). Haiku/Sonnet/Opus 5.5 IDs verified; Fable 5.1 not available on this account, so `hardest` pins to `claude-opus-5.5`.
- **S4 Timing:** DONE (see `spikes/S4-result.md`). 3 s timeout, exit 1 and bad JSON are all fail-open, silent to the user, hook killed. Adapter must always exit 0 and must not fork.

**Unit tests (stdlib `unittest`):**
- Feed fixture payloads to `transform()` with `JEV_ROUTER_HOME` set to a temp dir and `router.URL` pointing at `fake_jev.py`.
- Assertions:
  - control phrases rewrite the prompt;
  - OFF gives no output;
  - `/` and `!` give no output;
  - a secret gives no network call;
  - the first prompt of a session is never treated as a follow-up, and the second short "yes" is;
  - p < 0.60 gives no output;
  - each size produces the right agent in the note;
  - Jev timeout or HTTP 500 gives no output and exit 0;
  - a payload that already contains the note is left unchanged.

**End-to-end:**
- `copilot -p` with the router ON for four canned prompts, one per size. Assert `decisions.log` routes and the `— done by` footer.
- Check `jev router status` counts.

## 6. Phased task list

| Phase | Tasks | Exit criterion |
|---|---|---|
| 0 Spikes | S1-S4 above | Decide Tier 1 vs Tier 2; pin model IDs |
| 1 Core port | Scaffold the project; copy `router.py` verbatim; write `jev_copilot.py` (`transform`, CLI modes, session tracking); 4 agent files; hook template; unit tests + fake Jev | `python3 -m unittest` green |
| 2 Installer | `install.sh` / `uninstall.sh` (bash, idempotent, backups, `COPILOT_HOME`-aware); skill `/jev-router`; README + SECURITY (note the Keychain and that rewritten prompts persist in session history) | Fresh install, re-install and uninstall leave `~/.copilot` clean |
| 3 Fallbacks **DONE 2026-10-30; `jevcp` live PASS 2026-11-02** | If S1 fails: `jev_mcp.py` + `sessionStart` hook (Tier 2). Optional: `bin/jevcp` (Tier 3); `statusLine` showing the last route | Offline: 41 tests green incl. MCP over a pipe, `size`/`jevcp` with stub copilot, statusline, installer round-trip. Live: `jevcp` PASS (`spikes/JEVCP-live-result.md`); Tier 2 and status line not run live |
| 4 Evaluate | 1 week of use; compare against `--model auto --auto-tier balance` on cost (premium requests via `/usage`) and quality | Keep, tune `MIN_SURE`, or drop |
| 5 Package | Optional Copilot plugin; share the adapter with the VS Code plan (same `~/.copilot` files) | `copilot plugin install` works |

## 7. Risks

- **S1 fails** (command output ignored for `userPromptTransformed` too). Use Tier 2.
- **Rewritten prompt persists in history.** The routing note is replayed on resume and visible to later turns. Keep it short. The idempotency guard prevents stacking notes.
- **Copilot billing differs from Anthropic token pricing.** Routing tiny jobs to a subagent may *cost* more premium requests than it saves. Measure in Phase 4.
- **Hooks Preview churn.** Field names have changed in 2026; pin the CLI version in the README and re-run S1 after updates.
