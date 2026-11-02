# 01 - Analysis of `jev_router` (Claude Code model router)

Repository: `~/Code/GitHub/TechPreacher/jev_router` (branch `main`, 2 commits: `dea7d22` Initial commit 2026-10-27, `b412240` Adds keychain read 2026-10-28). Read-only; nothing was changed.

Size: 369 lines of code (`router.py` 242, `settings_hook.py` 69, `install.sh` 46, `uninstall.sh` 12) plus four 14-line agent files and docs. Python standard library only.

## 1. Purpose

Route every Claude Code user message to the *smallest* Claude model that can do the job well. An external classifier (TypeSafe **Jev**, `jev-latest`, at `https://api.typesafe.ai/v1/systemone`) answers one typed "choice" question about the message. The main session is then told to delegate the job to one of four helper subagents, each pinned to a different model:

| Size | Jev criterion (verbatim from `QUESTION`) | Agent | Frontmatter `model` | Footer line claims |
|---|---|---|---|---|
| tiny | A lookup, a rename, or a one-line answer | `jev-tiny` | `haiku` | Claude Haiku 5.5 |
| everyday | A normal email, post, or short document | `jev-everyday` | `sonnet` | Claude Sonnet 5.5 |
| large | A multi-step build, research, or a full report | `jev-large` | `opus` | Claude Opus 5.5 |
| hardest | Strategy, or a job where a wrong call is expensive | `jev-hardest` | `fable` | Claude Fable 5.1 |

## 2. Architecture and data flow

```
user types message in Claude Code
  -> UserPromptSubmit hook (~/.claude/settings.json)
     command: python3 -I "$HOME/.claude/jev-router/router.py" hook   (timeout 3 s)
     stdin: hook JSON {prompt, transcript_path, ...}
  -> router.py hook()
     1. "jev router on|off|status" (case-insensitive, trailing . or ! stripped)
          -> print {"decision":"block","reason":<status text>}  (message never reaches the model)
     2. empty / starts with "/" or "!" / router OFF  -> exit 0, no output
     3. decide():
          SECRETS regex hit            -> route "skipped_private"   (no network)
          short follow-up (see 4)      -> route "self_followup"     (no network)
          ask_jev() POST, 1.5 s timeout:
             exception                 -> "self_error"
             p(top choice) < 0.60      -> "self_unsure"
             else                      -> "tiny"|"everyday"|"large"|"hardest"
     4. record(): bump counters in state.json (flock), append JSON line to decisions.log
     5. if route is a size: print
          {"systemMessage": "Jev → large (83%) → jev-large",
           "hookSpecificOutput": {"hookEventName":"UserPromptSubmit",
                                  "additionalContext": "[jev-router] Jev sized this message as LARGE ... Delegate the job to the `jev-large` subagent (Agent tool, subagent_type \"jev-large\", runs on Claude Opus 5.5) ..."}}
  -> Claude Code shows systemMessage in the UI, appends additionalContext to the model context
  -> main model (whatever the session runs) reads the note and calls the Agent tool
  -> ~/.claude/agents/jev-<size>.md subagent runs on its pinned model, returns result
  -> main model relays it verbatim incl. "— done by <model> (jev-<size>)"
```

`main()` wraps `hook()` in `try/except Exception: pass` and always `sys.exit(0)`: the hook is fail-open by construction.

## 3. Claude Code extension points used

| Extension point | How it is used | Contract relied on |
|---|---|---|
| `hooks.UserPromptSubmit` in `~/.claude/settings.json` | One entry `{"hooks":[{"type":"command","command":"python3 -I \"$HOME/.claude/jev-router/router.py\" hook","timeout":3}]}` (no `matcher`) | stdin is JSON with `prompt` and `transcript_path`; stdout JSON is parsed on exit 0 |
| Hook output `hookSpecificOutput.additionalContext` | Injects the `[jev-router]` routing note into the model's context for this turn | Claude Code appends it as context, invisible to the user |
| Hook output `systemMessage` | One-line UI notice `Jev → <size> (p%) → <agent>` | Shown to the user, not the model |
| Hook output `{"decision":"block","reason":...}` | Implements the in-chat `jev router on/off/status` commands: prompt is erased, reason shown | Blocking UserPromptSubmit prevents the model turn |
| Exit code 0 + empty stdout | "do nothing" on every non-routing path | Non-zero would surface errors; 2 would block - deliberately never used |
| Subagents `~/.claude/agents/*.md` | Frontmatter `name`, `description` ("Use only when a [jev-router] note ... says to delegate"), `model` (`haiku`/`sonnet`/`opus`/`fable` aliases). No `tools:` key, so helpers inherit all tools | Loaded at session start ("start a new session" in install output) |
| Agent tool (`subagent_type`) | The routing note names the exact `subagent_type` | Main model must comply - it is an instruction, not a mechanism |

There is no MCP server, no slash command, no skill, no statusline. Everything rides on one hook + four agent files.

## 4. Classification and privacy logic

Order matters: secrets first, then follow-ups, then the network call.

- **Kept fully local (never sent):**
  - prompts starting with `/` (slash commands) or `!` (bash mode);
  - empty prompts; everything while the router is OFF;
  - the three `jev router ...` control phrases;
  - **secret-looking text** - regex `SECRETS` (case-insensitive): `sk-[A-Za-z0-9_-]{16,}` (OpenAI/Anthropic-style keys), `-----BEGIN [A-Z ]*PRIVATE KEY-----`, `\bpassword\s*[:=]`, `\bapi[_ -]?key\s*[:=]`, `\bgh[pousr]_[A-Za-z0-9]{20,}` (GitHub tokens) -> counted as `skipped_private`;
  - **short follow-ups** (`is_followup`): only if the session has history (`transcript_path` exists and size > 0) AND the prompt is <= 12 whitespace-separated words AND either starts with an acknowledgement (`yes|ok|sure|go ahead|do it|thanks|continue|perfect|...`) OR contains a back-reference word (`that|this|it|those|these|them|above|previous|earlier|last one|again|instead|shorter|longer|simpler|more|less`) -> `self_followup`.
- **Sent to TypeSafe:** everything else, truncated to the first `MAX_CHARS = 6000` characters, as `{"model":"jev-latest","state":{"message":...},"questions":{"size":{"type":"choice",...}}}` with `Authorization: Bearer <key>`.
- **Confidence gate:** `MIN_SURE = 0.60` on the probability of Jev's chosen option; below -> `self_unsure` (main model handles it).
- **API key:** `TYPESAFE_API_KEY` env var, else macOS Keychain generic password with service `TYPESAFE_API_KEY` via `/usr/bin/security find-generic-password -w -s ...` (1 s timeout). The Keychain fallback exists because the Claude desktop app launches hooks without the user's shell env.

## 5. State handling

- Directory: `$JEV_ROUTER_HOME` or `~/.claude/jev-router/`.
- `state.json`: `{enabled, counts{<route>: n}, jev_calls, input_tokens, errors, last_error, since}`. Read-modify-write under an exclusive `fcntl.flock` on `state.json.lock`, written via `state.json.tmp` + `os.replace` (atomic).
- `decisions.log`: JSON lines `{t, route, chars, size?, p?, confidence?, tokens?, ms?, error?}` - never the message text.
- Cost estimate: `input_tokens * $0.042 / 1M`.
- Toggle: in chat (`jev router on|off|status`, handled by the hook via `decision: block`) or from a shell (`router.py on|off|status|reset`). `reset` zeroes stats but keeps `enabled`. `since` is set on first enable.

## 6. Install / uninstall mechanics

`install.sh` (bash, `set -euo pipefail`):
1. requires `python3`; validates existing `~/.claude/settings.json` is JSON (aborts with nothing changed otherwise);
2. copies `router.py` + `files/README.md` to `~/.claude/jev-router/`;
3. copies `jev-*.md` to `~/.claude/agents/`, backing up a *changed* existing file to `<name>.bak-<timestamp>` first (`cmp -s`);
4. `settings_hook.py add`: timestamped `.bak-*` of settings.json, removes any entry whose command contains `jev-router/router.py` (idempotency marker), appends the new entry, atomic write;
5. creates state OFF only if `state.json` does not exist (re-install keeps on/off + stats);
6. warns if `TYPESAFE_API_KEY` is not set in the current shell; tells the user to restart Claude Code.

`uninstall.sh`: `settings_hook.py remove` (also writes a backup), deletes the four agent files and the whole `~/.claude/jev-router/` (stats included). No confirmation.

## 7. Limits and caveats admitted by the code/docs

- Claude Code cannot switch the **main** session model per message; the main model still reads every message and every helper reply. Savings only come from work the helper does (`files/README.md` "Limits").
- Helpers see only the prompt the main model writes for them, not the conversation.
- Secret filter is "best-effort, not a guarantee" (`SECURITY.md`).
- Every failure is silent (exit 0, no output); diagnose via `jev router status` -> `last error`.

## 8. Fragile or notable points (my findings)

1. **Delegation is advisory.** The routing note is just context; nothing enforces that the main model calls the Agent tool. Compliance depends on the main model.
2. **Tiny-job overhead may exceed savings.** Spawning a subagent costs the subagent's system prompt + tool schemas + the main model reading the result. For "tiny" jobs, delegation can cost more than answering directly - especially when the main model is already Haiku/Sonnet. The router has no "main model is already small enough" check (hook input does not say which model the session runs).
3. **Upward routing.** If the main session runs Haiku and Jev says `hardest`, the router *upgrades* to Fable. So it is a quality/cost balancer, not purely a cost saver.
4. **Follow-up heuristic is broad.** Any <= 12-word prompt containing `it`, `this`, `more`, `less`... stays local (e.g. "rename it to foo", "explain this function"). Conservative (no network) but means short real tasks are never routed.
5. **`has_history` uses `transcript_path` size > 0.** If Claude Code writes metadata to the transcript before the first user prompt, the first message could be treated as having history. Low impact.
6. **Timeout is per socket operation.** `urlopen(timeout=1.5)` bounds connect/read individually, not DNS or total time; plus up to 1 s for the Keychain call. The 3 s hook timeout is the real ceiling; Claude Code kills the hook and the turn proceeds (fail-open), but the user waits up to 3 s.
7. **Secret regex gaps.** Misses AWS `AKIA...` keys, Google `AIza...`, Slack `xox[abp]-`, JWTs (`eyJ...`), Azure connection strings (`AccountKey=`), `.env` dumps like `SECRET=`/`TOKEN=`, `ghs_`/`github_pat_` fine-grained PATs (only `gh[pousr]_` matched). Also false positives on docs that mention `password:`.
8. **Doc drift after `b412240`.** `SECURITY.md` still says "The key is read from the `TYPESAFE_API_KEY` environment variable at hook time"; `install.sh`'s warning likewise only mentions `export`. The Keychain fallback is documented only in `files/README.md`.
9. **Footer lines hard-code versions** (`— done by Claude Opus 5.5`) while frontmatter uses moving aliases (`opus`). When the alias moves, the footer lies.
10. **`decisions.log` grows forever** (no rotation), appended outside the lock (fine for small lines on POSIX `O_APPEND`).
11. **`settings_hook.py remove` on a machine without settings.json** creates `{}` - harmless, slightly surprising.
12. **macOS-only Keychain path**; on Linux the fallback silently returns None (fine, but README says macOS or Linux).
13. **Control phrases are exact.** `jev router on please` is sent to the model (and to Jev if ON).
14. **Python start-up cost on every message** even when OFF (~30-60 ms, `python3 -I` helps).
15. Helpers have **all tools** (no `tools:` restriction) and run with the same permission mode as the session.

Overall: small, careful, fail-open design; the clever part is using the hook's `additionalContext` + `decision: block` to build both the router and an in-chat control surface with zero UI code.
