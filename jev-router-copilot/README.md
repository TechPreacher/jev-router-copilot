# Jev model router for GitHub Copilot

Routes each message to the smallest GitHub Copilot model that can do the job well. TypeSafe Jev sizes the job,
and one of four helper agents does it: Claude Haiku 5.5, Sonnet 5.5, Opus 5.5, or a high-effort Opus 5.5 for the
hardest jobs. The main model stays in charge of the conversation and relays each helper's result.

This is the Copilot port of [jev_router](https://github.com/TechPreacher/jev_router) for Claude Code. The routing
logic (`router.py`) is the same file, copied unchanged. Only the hook and the helper agents differ.

**Status: Phase 3.** Phase 1 (the hook, Tier 1) is built and passed live in the CLI and the VS Code Copilot harness.
Phase 3 adds the optional fallbacks (Tier 2 MCP tool, Tier 3 `jevcp`, status line); `jevcp` passed live, the rest is
tested offline only. The per-size model configuration passed live in the CLI on 2026-11-02. See
[Fallbacks](#fallbacks-optional), [Models](#models) and [Limits](#limits).

## Requirements

- macOS (the Keychain fallback is macOS only) or Linux. `python3` with the standard library only.
- GitHub Copilot CLI (`copilot`), or VS Code with the Copilot harness, on an account that has
  `claude-haiku-5.5`, `claude-sonnet-5.5` and `claude-opus-5.5`.
- A TypeSafe API key in `TYPESAFE_API_KEY` (shell environment) or in the macOS Keychain. The Keychain is the
  reliable choice, because VS Code started from the Dock runs hooks without your shell environment. Store it once
  (you are prompted for the value, so it stays out of shell history):

  ```bash
  security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w
  ```

  See [SECURITY.md](SECURITY.md) for how the key is read.

## Install

```bash
cd jev-router-copilot   # this project's checkout
./install.sh
```

`install.sh` writes to `${COPILOT_HOME:-~/.copilot}`:

| Path | What |
|---|---|
| `jev-router/router.py` | the core, verbatim from jev_router |
| `jev-router/jev_copilot.py` | the adapter: the hook, the shell control, `model` (per-size models), `size` (for `jevcp`) and `session` |
| `jev-router/models.json` | your per-size model choices (created by the first `model` change; never overwritten by a re-install) |
| `jev-router/agents/jev-*.agent.md.tmpl` | the agent templates, so `model` can re-render an agent file without the checkout |
| `jev-router/jev_statusline.py` | status line printer (not registered; see [Fallbacks](#fallbacks-optional)) |
| `jev-router/bin/jevcp` | Tier 3 wrapper that routes the main model (not on PATH; see [Fallbacks](#fallbacks-optional)) |
| `hooks/jev-router.json` | the hook file, rendered from the template with absolute paths |
| `agents/jev-{tiny,everyday,large,hardest}.agent.md` | the four helper agents, rendered from the templates and `models.json` |
| `skills/jev-router/SKILL.md` | the `/jev-router on\|off\|status\|reset\|model ...` skill |

With `./install.sh --tier2` it also writes `hooks/jev-router-session.json` and `jev-router/jev_mcp.py`. The installer
prints the `statusLine` and `mcpServers` snippets and never writes `settings.json`, `mcp-config.json` or your shell rc.

It is idempotent: a changed file is kept as `<name>.bak-<timestamp>` before it is replaced, and an existing on/off
switch and stats are kept. A fresh install leaves the router OFF. The installer then runs a self-test: a scratch
state dir (OFF, no network), where the hook must print nothing and exit 0.

Then start Copilot CLI, or open a Copilot-harness chat in VS Code, and type `jev router on`.

## Uninstall

```bash
./uninstall.sh
```

This removes the hook files (Tier 1 and Tier 2), the four helper agents, the skill, and the `jev-router` directory
(including `jevcp`, the status line and the MCP server file, and the stats). Entries you pasted into `settings.json` or
`mcp-config.json` are not touched; the script tells you if it finds them.
Backups made by the installer are listed, not deleted.

## Control phrases

Type these as a normal message. The hook performs the action, and the model replies with the status text.

| Message | Effect |
|---|---|
| `jev router on` | routing ON (the stats start counting from this time) |
| `jev router off` | routing OFF |
| `jev router status` | ON/OFF, route counts, Jev calls and tokens, cost, last error |
| `jev router reset` | clears the counters and last error; keeps ON/OFF |
| `jev router model` | the model, effort, policy and label per size |
| `jev router model <size> <model-id> [--label "Name"] [--effort low\|medium\|high\|none] [--policy required\|preferred]` | change one size and re-render its agent file |
| `jev router model reset` | back to the defaults: deletes `models.json` and re-renders all four agent files |
| `jev router models` | the models your account can use, grouped by the size they fit |

From a shell, or with the skill: `python3 -I ~/.copilot/jev-router/jev_copilot.py on|off|status|reset|model ...`, or
`/jev-router on|off|status|reset|model ...` in chat.

## How it works

1. You send a message. Copilot runs the `userPromptTransformed` hook: `python3 -I jev_copilot.py transform`, with a
   3-second timeout. The payload has the `sessionId`, your `prompt`, and `transformedPrompt`.
2. Control phrases: the adapter performs the action and rewrites the prompt to
   "Reply with exactly the following text and nothing else:" plus the status text. The model echoes it.
3. Otherwise the adapter skips the message when it is OFF, is a slash or `!` command, is already routed, or looks
   like a secret. It also skips a short follow-up in a session that already has a prompt. Copilot gives hooks no
   transcript, so the adapter remembers the last 200 session IDs in `state.json`.
4. The rest goes to Jev with the original `prompt`, not `transformedPrompt`. Jev's answer is a size and a
   probability. If the probability is at least 0.60 the adapter appends a routing note to `transformedPrompt`,
   after the workspace context. Otherwise the main model handles the message. The note reads:

   > [jev-router] Jev sized this message as TINY (p=0.83). Delegate the job to the `jev-tiny` custom agent via the
   > task tool. Give it a self-contained prompt: the user's message plus any context it needs. Relay its result to
   > the user as-is, keeping its final 'done by' line. Don't redo the work yourself. If the agent is unavailable or
   > fails, do the job yourself and say the router fell back.

5. The main model delegates to the named `jev-<size>` agent, relays its result, and keeps its final
   `— done by <model> (jev-<size>)` line.

Any failure (no key, Jev slow or down, bad JSON, HTTP error) prints nothing and exits 0. The message goes through
unchanged and the error goes to `state.json`.

## Models

Defaults (what a fresh install renders):

| Size | Helper agent | Copilot model ID | Effort | Footer |
|---|---|---|---|---|
| tiny: a lookup, a rename, a one-line answer | `jev-tiny` | `claude-haiku-5.5` | - | Claude Haiku 5.5 |
| everyday: a normal email, post or short document | `jev-everyday` | `claude-sonnet-5.5` | - | Claude Sonnet 5.5 |
| large: a multi-step build, research, a full report | `jev-large` | `claude-opus-5.5` | - | Claude Opus 5.5 |
| hardest: strategy, or a wrong call is expensive | `jev-hardest` | `claude-opus-5.5` | high | Claude Opus 5.5 |

### Changing the model for a size

Copilot CLI and VS Code offer many models, and the right one per size depends on your plan, your taste and what the
account is entitled to. Change a size at any time, also after the router is installed:

```bash
python3 -I ~/.copilot/jev-router/jev_copilot.py model                         # show the table
python3 -I ~/.copilot/jev-router/jev_copilot.py models                        # models you can use, grouped by size
python3 -I ~/.copilot/jev-router/jev_copilot.py model large gpt-6.1-sol       # change one size
python3 -I ~/.copilot/jev-router/jev_copilot.py model hardest claude-opus-5.5 --effort high --policy preferred
python3 -I ~/.copilot/jev-router/jev_copilot.py model tiny claude-sonnet-5.5 --label "Sonnet for lookups"
python3 -I ~/.copilot/jev-router/jev_copilot.py model reset                   # defaults: deletes models.json, re-renders all four agents
```

In chat the same works as `jev router model large gpt-6.1-sol` (or `/jev-router model large gpt-6.1-sol`), and the
reply shows the new table. Each change:

- is saved to `~/.copilot/jev-router/models.json` (the source of truth; a re-install keeps it),
- re-renders that one `agents/jev-<size>.agent.md` from its template in `jev-router/agents/`, since Copilot CLI and
  VS Code read `model:`, `reasoningEffort:` and `model-policy:` from the agent file and there is no other way to pin a
  helper's model,
- updates the label in the routing note, the status text and the helper's `— done by <label> (jev-<size>)` footer.
  The label is derived from the ID (`gpt-6.1-sol` -> `GPT 6.1 Sol`) unless you pass `--label`.

New Copilot sessions use the change (both clients read agent files at session start; a running session keeps the old
pin). Options: `--effort low|medium|high|none` sets `reasoningEffort:` in the agent file (undocumented and ignored by
the CLI today, see Limits) and the `--reasoning-effort` flag `jevcp` passes; `--policy required` (default) makes the
helper fail if the model is unavailable, which the routing note handles by telling the main model to do the job
itself, while `--policy preferred` lets Copilot fall back to another model silently.

Validation is local: the ID must look like a Copilot model ID (lowercase, digits, dots, dashes). Entitlement is not
checked at `model` time, because only the CLI knows it: an ID your account lacks (for example `claude-fable-5.1` on
the tested account) shows up as a helper failure on first use. `models` tells you beforehand, see below.
Do not edit the rendered agent files by hand; the next `model` change or re-install rewrites them. Edit the templates
in `jev-router/agents/` instead if you want to change the helper's instructions.

### Which models fit which size

`models` (or `jev router models` in chat, or `/jev-router models`) lists the models your account can use, grouped by
the size they fit and sorted by ID, with GitHub's display name, price category, preview flag and the reasoning
efforts the model supports. The current choice per size is starred:

```
  tiny (lightweight)
  * claude-haiku-5.5    Claude Haiku 5.5   price low, effort low/medium/high/xhigh/max
    gpt-5.6-luna        GPT-5.6 Luna       price low, effort none/low/medium/high/xhigh/max
  everyday (versatile)
  * claude-sonnet-5.5   Claude Sonnet 5.5  price medium, effort low/medium/high/xhigh/max
  large (powerful)
  * claude-opus-5.5     Claude Opus 5.5    price high, effort low/medium/high/xhigh/max
    gpt-6.1-sol         GPT-6.1 Sol        price medium, effort low/medium/high/xhigh/max
  hardest (powerful with reasoning effort high; set it with --effort high)
  * claude-opus-5.5     ...
```

The grouping is GitHub's own: the catalog that Copilot CLI fetches at session start tags each model with a
model-picker category, and `lightweight`, `versatile` and `powerful` map onto tiny, everyday and large. hardest
repeats the powerful models that support a high reasoning effort. Only models the account is entitled to appear,
so an ID missing here will fail as a helper. Models the CLI hides from its own picker (legacy GPT-4 variants,
embeddings) are left out.

The catalog is read from the newest `~/.copilot/logs/process-*.log` that holds one. Copilot CLI writes it only with
`"logLevel": "all"` in `~/.copilot/settings.json`; without that, `models` falls back to the flat list of IDs that
`copilot help config` accepts (schema only, no entitlement) and says how to get the grouped one. The entries are as
old as that log; start a Copilot session to refresh. Nothing is fetched from the network, and the log is only read
for that one line.

Tested: live on CLI 1.0.105 on 2026-11-02. `model tiny claude-sonnet-5.5 --label "Sonnet Tiny Test"` on the
installed copy made the next `copilot -p` session run `jev-tiny` on `claude-sonnet-5.5` (`subagent.started` in
`events.jsonl`) with the test label in the footer; `model reset` put Haiku back. VS Code reads the same agent files,
but the changed-model case was not re-run there. `--effort`, `--policy preferred` and an unentitled ID are offline-tested only.

## Fallbacks (optional)

Phase 3. `jevcp` (one-shot `-p`) is live-tested on CLI 1.0.105; `jevcp -i`, Tier 2 and the status line are
offline-tested only. None is wired into your Copilot settings by default.

### Tier 2: `jev_size` MCP tool (use only if Tier 1 stops working)

Tier 1 (the `userPromptTransformed` hook) is the normal path. Use Tier 2 only when a Copilot CLI update stops the
rewrite from reaching the model. Tier 2 uses documented features only:

- `sessionStart` hook (`hooks/jev-router-session.json`) returns `additionalContext` with a standing rule: call the
  `jev_size` tool for each new request that is not a short follow-up, then do what the result says.
- `jev_mcp.py` is a stdlib stdio MCP server (JSON-RPC 2.0, one tool). `jev_size` runs the same `decide()`/`record()`
  and returns the same routing note as the hook. When the router is OFF it says so and writes nothing.

Install with `./install.sh --tier2`. The installer prints the `mcpServers` snippet; merge it into
`~/.copilot/mcp-config.json` yourself:

```json
{"mcpServers": {"jev-router": {"type": "local", "command": "python3",
                               "args": ["-I", "<install dir>/jev_mcp.py"], "tools": ["*"]}}}
```

Downsides: the model decides whether to call the tool, and each message costs one extra tool round-trip on the main
model. The standing rule is sent at session start, so it also applies while the router is OFF (the tool then returns
the OFF text). Do not run Tier 1 and Tier 2 together for long: both size each message.

### Tier 3: `jevcp` (routes the main model)

`jevcp` sizes a prompt with Jev and then runs Copilot CLI on the model Jev picked. This is the one thing Tier 1 cannot
do: it changes the main model, and for `hardest` it adds `--reasoning-effort high`.

```bash
export PATH="$HOME/.copilot/jev-router/bin:$PATH"   # or fish_add_path; the installer prints the line
jevcp "Research the main options for migrating our reporting from Postgres to ClickHouse."
jevcp -i "Should we rewrite billing in-house or buy a vendor?"   # interactive session
```

Mapping: tiny `claude-haiku-5.5`, everyday `claude-sonnet-5.5`, large `claude-opus-5.5` with `--reasoning-effort medium`,
hardest `claude-opus-5.5` with `--reasoning-effort high`. Kept by the main model, or router OFF: plain `copilot` on
your default model. Each `jevcp` run starts a new session, so it sizes every prompt as a first request. Inside the
copilot run `JEV_ROUTER_PRESIZED=1` stops the Tier 1 hook from sizing the same prompt again. Control phrases still
work through the hook. Trade-offs: no mid-conversation switching (`--continue` with another model is unverified); with `-i` the
`JEV_ROUTER_PRESIZED` variable stays set for the whole interactive session, so later messages in it are not sized by the
Tier 1 hook either (the main model is already the one Jev picked); and the prompt is on argv, which `ps` can show.

### Status line

`jev_statusline.py` prints one line from `state.json` and the last entry of `decisions.log`:
`Jev ON · large 77%`, `Jev ON · kept (unsure)`, `Jev ON · no decisions yet`, or `Jev OFF`. It reads no message text
and fails open (`Jev ?`). The installer prints this snippet; paste it into `~/.copilot/settings.json` yourself:

```json
"statusLine": {"type": "command", "command": "python3 -I \"<install dir>/jev_statusline.py\""}
```

It replaces the Claude Code `systemMessage` line ("Jev → large (83%)") as a persistent line below the input, not as a
message in the transcript. It shows the last decision. Its placement and refresh timing are documented but not yet checked in a live
Copilot session.

## Limits

- **`python3` must be on your login shell's PATH.** The hook runs a bare `python3`. VS Code (terminal or Dock launch) and
  the Copilot CLI resolve your login-shell environment, so this is normally true; if routing is silent, put an absolute
  interpreter path in `~/.copilot/hooks/jev-router.json`.
- **No block.** Copilot hooks cannot swallow a message. A control phrase costs one cheap model turn that echoes
  the status. The status is also in the transcript.
- **No built-in UI line.** Claude Code's "Jev → large (83%)" line has no Copilot equivalent. The optional status line
  (see [Fallbacks](#fallbacks-optional)) approximates it.
- **VS Code ignores `additionalContext` from command hooks**, so the note is appended to `transformedPrompt` instead.
- **Fable is not available** on the tested account, so `hardest` runs on Opus 5.5, the same model as `large`.
  The agent file asks for `reasoningEffort: high`, but the CLI reports `medium` for the helper and the key is
  undocumented, so today the two helpers only differ in name, note and stats. Once the account has Fable:
  `python3 -I ~/.copilot/jev-router/jev_copilot.py model hardest claude-fable-5.1 --effort high`.
- **Hooks are Preview**, and the Copilot CLI updates itself. Re-run the spikes (S1 for the CLI, S6 for VS Code) after
  an update and pin the version you test with.
- **Silent failures.** Copilot does not show hook errors or timeouts. Check `jev router status`, `last error`.
- **Time budget.** The hook is killed after 3 seconds. Jev gets 1.5 seconds, and a Keychain read gets 1 second, so a
  slow Keychain can cost a whole message's routing.
- **Rewritten prompts persist** in the session history, and are replayed on `--resume`. The note is short and an
  idempotency check stops notes from stacking.
- **The main model still reads every message** and every helper reply. Savings come from the helper's model
  price, not from skipping the main model. Helper calls are subagent work and may count toward premium requests. Measure
  before relying on it.
- **Helper prompts are skipped.** Copilot also runs the hook for a helper's own first prompt (the payload then
  carries `agentId`, `agentType` and `parentAgentId`). The adapter ignores those, so a routing note is never nested
  inside a helper and cannot start a delegation loop. Found in the first live run; fixed on 2026-10-30.
- **Only the prompt is sized.** Jev sees one message, not the conversation, so a short message that depends on earlier
  context can be misrouted. Follow-up detection is a heuristic.

## Privacy

When ON, the text of each sized message (as typed, first 6000 characters) goes to `api.typesafe.ai`. Slash commands,
`!` commands, short follow-ups and secret-looking text stay local. Stats hold no message text, but Copilot's session
history keeps the rewritten prompt. Details in [SECURITY.md](SECURITY.md). For the VS Code harness, check that
sending prompts to TypeSafe fits your organisation's Copilot data policy.

## Testing

Offline unit tests (stdlib `unittest`; a local fake of the Jev API in `tests/fake_jev.py`):

```bash
bash tests/run.sh
```

They cover control phrases, OFF, slash and `!`, secrets, follow-ups, the confidence threshold, each size's note,
timeouts and HTTP errors, the marker guard, bad input, the session bound, and the agent and hook files
(`test_adapter.py`, 18 cases). `test_phase3.py` (23 cases) covers the Tier 2 MCP server over a pipe, the `size` mode and
`jevcp` with a stub `copilot`, the status line, and an installer round-trip in a temporary `COPILOT_HOME`.
`test_models.py` (13 cases) covers the `model` command and chat phrase, flags and bad input, `reset`, a broken
`models.json` (hook fails open, `model` reports), `render-agents`, an install-then-change-then-reinstall round
trip on an installed copy, and `models` against a fixture catalog log (grouping, order, newest log, the chat
phrase, the fallback without a catalog).

End to end, with a real Copilot session (this costs credits, so run it deliberately):

1. Install (`./install.sh`), then start `copilot` and type `jev router on`.
2. Send one canned prompt per size:
   - tiny: `What is the HTTP status code for "not found"?`
   - everyday: `Draft a two-sentence thank-you email to a colleague who covered my shift.`
   - large: `Research the main options for migrating our reporting from Postgres to ClickHouse and write a full report with a comparison table.`
   - hardest: `Should we rewrite our billing system in-house or buy a vendor? Give me a strategy and the risks of each.`
3. Find the newest session: `ls -td ~/.copilot/session-state/*/ | head -1`. Its `events.jsonl` holds
   `hook.start` and `hook.end` events for `userPromptTransformed` (`hook.end` shows `success`), and each
   `assistant.message` ends with a `— done by ... (jev-<size>)` footer.
4. Check `tail -n 4 ~/.copilot/jev-router/decisions.log` for the four routes, and `jev router status` for the counts.
5. Changed model: `jev_copilot.py model tiny claude-sonnet-5.5 --label "Test"`, send the tiny prompt in a new
   session, and look for `subagent.started` with `"model": "claude-sonnet-5.5"` in `events.jsonl` and
   `— done by Test (jev-tiny)` in the reply. Then `model reset`.

Nothing in the tests runs `copilot`. The `events.jsonl` check is manual.

## Layout

```
jev-router-copilot/
  README.md  SECURITY.md  LICENSE
  install.sh  uninstall.sh
  files/
    router.py                    core, verbatim copy of jev_router/files/router.py
    jev_copilot.py               adapter: transform hook, on/off/status/reset, model (per-size models), size (jevcp), session (Tier 2)
    jev_mcp.py                   Tier 2 stdio MCP server with jev_size (opt-in: install.sh --tier2)
    jev_statusline.py            status line printer (snippet only, not registered)
    bin/jevcp                    Tier 3 wrapper: size, then copilot --model <id>
    hooks/jev-router.json.tmpl   hook file template (@JR@ = install dir)
    hooks/jev-router-session.json.tmpl  Tier 2 sessionStart template
    agents/jev-{tiny,everyday,large,hardest}.agent.md.tmpl   helper agent templates (rendered with models.json)
    skills/jev-router/SKILL.md   /jev-router skill template
  tests/
    run.sh                       python3 -m unittest discover -s tests -v
    test_adapter.py              offline tests of the hook and the packaging
    test_phase3.py               Tier 2 MCP, size mode, jevcp, status line, installer round-trip
    fake_jev.py                  local stand-in for api.typesafe.ai (query-string controlled)
```

## License

[MIT](LICENSE)
