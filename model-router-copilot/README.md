# Model router for GitHub Copilot

Routes each message to the smallest GitHub Copilot model that can do the job well. TypeSafe Jev or Microsoft
Decision-1 sizes the job,
and one of four helper agents does it: Claude Haiku 5.5, Sonnet 5.5, Opus 5.5, or a high-effort Opus 5.5 for the
hardest jobs. The main model stays in charge of the conversation and relays each helper's result.

This is the Copilot port of [model-router](https://github.com/TechPreacher/model-router) for Claude Code. The routing
logic (`router.py`) is the same file, copied unchanged. Only the hook and the helper agents differ.

**Status: Phase 3.** Phase 1 (the hook, Tier 1) is built and passed live in the CLI and the VS Code Copilot harness.
Phase 3 adds the optional fallbacks (Tier 2 MCP tool, Tier 3 `routercp`, status line); `routercp` passed live, the rest is
tested offline only. The per-size model configuration passed live in the CLI on 2026-11-02. See
[Fallbacks](#fallbacks-optional), [Models](#models) and [Limits](#limits).

## Requirements

- macOS, Linux or Windows. Python 3.8+ with the standard library only (`python3` on macOS and Linux; on Windows
  `python`, `python3` or `py -3`, whichever works first). Windows also needs PowerShell 7 (`pwsh`) on PATH, which is
  what Copilot CLI runs hooks with there (`winget install Microsoft.PowerShell`).
- GitHub Copilot CLI (`copilot`), or VS Code with the Copilot harness, on an account that has
  `claude-haiku-5.5`, `claude-sonnet-5.5` and `claude-opus-5.5`.
- A sizing backend: a TypeSafe API key in `TYPESAFE_API_KEY`, or a Microsoft Decision-1 deployment in Azure AI
  Foundry (`MODEL_ROUTER_AZURE_ENDPOINT` + `MODEL_ROUTER_AZURE_DEPLOYMENT`, see [Backends](#backends-typesafe-router-or-azure-decision-1)).
  Each value lives in the shell environment, the macOS Keychain, or the Windows Credential Manager. The key store is
  the reliable choice, because VS Code started from the Dock or the Start menu runs hooks
  without your shell environment. Store it once (you are prompted for the value, so it stays out of shell history):

  ```bash
  security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w          # macOS
  ```

  ```powershell
  $k = Read-Host 'TypeSafe API key' -AsSecureString                           # Windows (generic credential)
  cmdkey /generic:TYPESAFE_API_KEY /user:$env:USERNAME /pass:((New-Object System.Net.NetworkCredential('', $k)).Password)
  ```

  On Linux use the environment variable. `python3 -I ~/.copilot/model-router/router_copilot.py key` says where the key was
  found, never its value. See [SECURITY.md](SECURITY.md) for how the key is read.

## Install

```bash
cd model-router-copilot   # this project's checkout
./install.sh
```

```powershell
cd model-router-copilot   # Windows: the PowerShell twin, same files, same checks
.\install.ps1          # or: pwsh -ExecutionPolicy Bypass -File .\install.ps1
```

`install.sh` (and `install.ps1`) writes to `${COPILOT_HOME:-~/.copilot}`:

| Path | What |
|---|---|
| `model-router/router.py` | the core, verbatim from model-router |
| `model-router/router_copilot.py` | the adapter: the hook, the shell control, `model` (per-size models), `size` (for `routercp`) and `session` |
| `model-router/router_compat.py` | Windows shims: a stand-in for `fcntl`, the Credential Manager key, UTF-8 stdio (no-op elsewhere) |
| `model-router/models.json` | your per-size model choices (created by the first `model` change; never overwritten by a re-install) |
| `model-router/agents/router-*.agent.md.tmpl` | the agent templates, so `model` can re-render an agent file without the checkout |
| `model-router/router_statusline.py` | status line printer (not registered; see [Fallbacks](#fallbacks-optional)) |
| `model-router/bin/routercp`, `bin/routercp.ps1` | Tier 3 wrapper that routes the main model, bash and PowerShell (not on PATH; see [Fallbacks](#fallbacks-optional)) |
| `hooks/model-router.json` | the hook file, rendered from the template with absolute paths; a `bash` command for macOS and Linux and a `powershell` command for Windows (Copilot picks by OS) |
| `agents/router-{tiny,everyday,large,hardest}.agent.md` | the four helper agents, rendered from the templates and `models.json` |
| `skills/model-router/SKILL.md` | the `/model-router on\|off\|status\|reset\|model ...` skill |

With `./install.sh --tier2` (`.\install.ps1 -Tier2`) it also writes `hooks/model-router-session.json` and
`model-router/router_mcp.py`. The installer prints the `statusLine` and `mcpServers` snippets and never writes
`settings.json`, `mcp-config.json`, your shell rc or your PowerShell profile.

On Windows the hook, the skill and the printed snippets call the interpreter by its full path (the first of `python`,
`python3`, `py -3` that works), because a bare `python` may hit the Microsoft Store stub and VS Code may not see your
PATH. After a Python upgrade that changes the path, re-run `.\install.ps1`.

It is idempotent: a changed file is kept as `<name>.bak-<timestamp>` before it is replaced, and an existing on/off
switch and stats are kept. A fresh install leaves the router OFF. The installer then runs a self-test: a scratch
state dir (OFF, no network), where the hook must print nothing and exit 0.

Then start Copilot CLI, or open a Copilot-harness chat in VS Code, and type `model router on`.

## Uninstall

```bash
./uninstall.sh      # Windows: .\uninstall.ps1
```

This removes the hook files (Tier 1 and Tier 2), the four helper agents, the skill, and the `model-router` directory
(including `routercp`, the status line and the MCP server file, and the stats). Entries you pasted into `settings.json` or
`mcp-config.json` are not touched; the script tells you if it finds them.
Backups made by the installer are listed, not deleted.

## Backends: TypeSafe Jev or Azure Decision-1

The sizing question can be answered by TypeSafe's hosted Jev (default) or by a
[Microsoft-Decision-1](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision)
deployment in your own Azure AI Foundry resource. Both take the same request and return the same answer shape, so
routing, thresholds and stats are identical. The Azure backend is active as soon as both of these are set:

| Name | Value | Where it may live |
|---|---|---|
| `MODEL_ROUTER_AZURE_ENDPOINT` | the Foundry resource endpoint, e.g. `https://<resource>.services.ai.azure.com` (with or without `/providers/microsoft`) | environment, Keychain, Credential Manager |
| `MODEL_ROUTER_AZURE_DEPLOYMENT` | the deployment name, e.g. `Decision-1` | same |
| `MODEL_ROUTER_AZURE_API_KEY` | optional: the deployment's API key, sent as an `api-key` header instead of an Entra token | same |
| `MODEL_ROUTER_AZURE_SCOPE` | optional: token scope for `az`, default `https://ai.azure.com/.default` | environment |
| `MODEL_ROUTER_BACKEND` | optional: `typesafe` forces TypeSafe even when the Azure values exist | environment |

Requests go to `<endpoint>/providers/microsoft/v1/systemone` with `model` set to the deployment name. The endpoint and
the deployment name are treated as secrets: `status` and `key` say which backend is active and where each value was
found, never the values. Store them like the API key (`security add-generic-password -U -a "$USER" -s MODEL_ROUTER_AZURE_ENDPOINT -w`
on macOS; `cmdkey /generic:MODEL_ROUTER_AZURE_ENDPOINT ...` on Windows, same `Read-Host` recipe as above).

**Token.** Without `MODEL_ROUTER_AZURE_API_KEY` the router authenticates with a Microsoft Entra bearer token from
`az account get-access-token` (sign in once with `az login`; the Azure CLI must be on PATH). `az` takes about 2.5 s and
the hook has 3, so the hook never calls it: it reads a token cached in `~/.copilot/model-router/azure-token.json`
(owner-only file, valid about an hour) and, when that is missing or has under ten minutes left, starts a detached
background refresh and lets the current message through unrouted once (`model router status` then shows
`last error: ... Azure token not cached yet`). `model router on` from a shell, and `routercp`, fetch the token and wait, so
the first routed message is not lost; in chat, `model router on` starts the refresh in the background. Live-tested
2026-11-04 from a shell against a real deployment (all four sizes answered, 420 to 500 ms; see
[`spikes/AZURE-live-result.md`](../spikes/AZURE-live-result.md)), not yet inside a Copilot session. Your identity needs
the `Cognitive Services User` role on the Foundry resource; being Owner of the subscription is not enough (401
PermissionDenied).

## Renamed from jev-router (2026-11-04)

The project was `jev-router` while TypeSafe Jev was its only sizing backend. With Azure Decision-1 added, the
backend-neutral parts carry neutral names: directory `model-router/`, hook `model-router.json`, skill `/model-router`,
agents `router-tiny|everyday|large|hardest`, phrases `model router ...`, scripts `router_copilot.py`,
`router_statusline.py`, `router_mcp.py`, `router_compat.py`, wrapper `routercp`, note tag `[model-router]`, and
environment names `MODEL_ROUTER_HOME`, `MODEL_ROUTER_URL`, `MODEL_ROUTER_PRESIZED`, `MODEL_ROUTER_BACKEND`,
`MODEL_ROUTER_AZURE_*`. `TYPESAFE_API_KEY` and the TypeSafe backend keep their names.

Running the installer over an old install moves `~/.copilot/jev-router` to `model-router` with its `models.json`, state
and stats, removes the old hook, agents, skill and scripts, and prints a note if `settings.json` or `mcp-config.json`
still point at the old paths (the installer never edits those). For one release the old names still work: `jev router
...` phrases, `JEV_ROUTER_HOME`, `JEV_ROUTER_PRESIZED`, `JEV_BACKEND`, `JEV_AZURE_*` (environment, Keychain and
Credential Manager), and the old `[jev-router]` note in replayed session history. Checked live on 2026-11-04 right after
migrating the author's `~/.copilot`: one tiny prompt in Copilot CLI got the `[model-router] Sized as TINY` note, ran on
`router-tiny` (claude-haiku-5.5) and ended with `— done by Claude Haiku 5.5 (router-tiny)`.

## Control phrases

Type these as a normal message. The hook performs the action, and the model replies with the status text.

| Message | Effect |
|---|---|
| `model router on` | routing ON (the stats start counting from this time) |
| `model router off` | routing OFF |
| `model router status` | ON/OFF, route counts, Jev calls and tokens, cost, last error |
| `model router reset` | clears the counters and last error; keeps ON/OFF |
| `model router model` | the model, effort, policy and label per size |
| `model router model <size> <model-id> [--label "Name"] [--effort low\|medium\|high\|none] [--policy required\|preferred]` | change one size and re-render its agent file |
| `model router model reset` | back to the defaults: deletes `models.json` and re-renders all four agent files |
| `model router models` | the models your account can use, grouped by the size they fit |

From a shell, or with the skill: `python3 -I ~/.copilot/model-router/router_copilot.py on|off|status|reset|model ...`, or
`/model-router on|off|status|reset|model ...` in chat.

## How it works

1. You send a message. Copilot runs the `userPromptTransformed` hook: `python3 -I router_copilot.py transform`, with a
   3-second timeout. The payload has the `sessionId`, your `prompt`, and `transformedPrompt`.
2. Control phrases: the adapter performs the action and rewrites the prompt to
   "Reply with exactly the following text and nothing else:" plus the status text. The model echoes it.
3. Otherwise the adapter skips the message when it is OFF, is a slash or `!` command, is already routed, or looks
   like a secret. It also skips a short follow-up in a session that already has a prompt. Copilot gives hooks no
   transcript, so the adapter remembers the last 200 session IDs in `state.json`.
4. The rest goes to Jev with the original `prompt`, not `transformedPrompt`. Jev's answer is a size and a
   probability. If the probability is at least 0.60 the adapter appends a routing note to `transformedPrompt`,
   after the workspace context. Otherwise the main model handles the message. The note reads:

   > [model-router] Sized as TINY (p=0.83). Delegate the job to the `router-tiny` custom agent via the
   > task tool. Give it a self-contained prompt: the user's message plus any context it needs. Relay its result to
   > the user as-is, keeping its final 'done by' line. Don't redo the work yourself. If the agent is unavailable or
   > fails, do the job yourself and say the router fell back.

5. The main model delegates to the named `router-<size>` agent, relays its result, and keeps its final
   `— done by <model> (router-<size>)` line.

Any failure (no key, Jev slow or down, bad JSON, HTTP error) prints nothing and exits 0. The message goes through
unchanged and the error goes to `state.json`.

## Models

Defaults (what a fresh install renders):

| Size | Helper agent | Copilot model ID | Effort | Footer |
|---|---|---|---|---|
| tiny: a lookup, a rename, a one-line answer | `router-tiny` | `claude-haiku-5.5` | - | Claude Haiku 5.5 |
| everyday: a normal email, post or short document | `router-everyday` | `claude-sonnet-5.5` | - | Claude Sonnet 5.5 |
| large: a multi-step build, research, a full report | `router-large` | `claude-opus-5.5` | - | Claude Opus 5.5 |
| hardest: strategy, or a wrong call is expensive | `router-hardest` | `claude-opus-5.5` | high | Claude Opus 5.5 |

### Changing the model for a size

Copilot CLI and VS Code offer many models, and the right one per size depends on your plan, your taste and what the
account is entitled to. Change a size at any time, also after the router is installed:

```bash
python3 -I ~/.copilot/model-router/router_copilot.py model                         # show the table
python3 -I ~/.copilot/model-router/router_copilot.py models                        # models you can use, grouped by size
python3 -I ~/.copilot/model-router/router_copilot.py model large gpt-6.1-sol       # change one size
python3 -I ~/.copilot/model-router/router_copilot.py model hardest claude-opus-5.5 --effort high --policy preferred
python3 -I ~/.copilot/model-router/router_copilot.py model tiny claude-sonnet-5.5 --label "Sonnet for lookups"
python3 -I ~/.copilot/model-router/router_copilot.py model reset                   # defaults: deletes models.json, re-renders all four agents
```

In chat the same works as `model router model large gpt-6.1-sol` (or `/model-router model large gpt-6.1-sol`), and the
reply shows the new table. Each change:

- is saved to `~/.copilot/model-router/models.json` (the source of truth; a re-install keeps it),
- re-renders that one `agents/router-<size>.agent.md` from its template in `model-router/agents/`, since Copilot CLI and
  VS Code read `model:`, `reasoningEffort:` and `model-policy:` from the agent file and there is no other way to pin a
  helper's model,
- updates the label in the routing note, the status text and the helper's `— done by <label> (router-<size>)` footer.
  The label is derived from the ID (`gpt-6.1-sol` -> `GPT 6.1 Sol`) unless you pass `--label`.

New Copilot sessions use the change (both clients read agent files at session start; a running session keeps the old
pin). Options: `--effort low|medium|high|none` sets `reasoningEffort:` in the agent file (undocumented and ignored by
the CLI today, see Limits) and the `--reasoning-effort` flag `routercp` passes; `--policy required` (default) makes the
helper fail if the model is unavailable, which the routing note handles by telling the main model to do the job
itself, while `--policy preferred` lets Copilot fall back to another model silently.

Validation is local: the ID must look like a Copilot model ID (lowercase, digits, dots, dashes). Entitlement is not
checked at `model` time, because only the CLI knows it: an ID your account lacks (for example `claude-fable-5.1` on
the tested account) shows up as a helper failure on first use. `models` tells you beforehand, see below.
Do not edit the rendered agent files by hand; the next `model` change or re-install rewrites them. Edit the templates
in `model-router/agents/` instead if you want to change the helper's instructions.

### Which models fit which size

`models` (or `model router models` in chat, or `/model-router models`) lists the models your account can use, grouped by
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
installed copy made the next `copilot -p` session run `router-tiny` on `claude-sonnet-5.5` (`subagent.started` in
`events.jsonl`) with the test label in the footer; `model reset` put Haiku back. VS Code reads the same agent files,
but the changed-model case was not re-run there. `--effort`, `--policy preferred` and an unentitled ID are offline-tested only.

## Fallbacks (optional)

Phase 3. `routercp` (one-shot `-p`) is live-tested on CLI 1.0.105; `routercp -i`, Tier 2 and the status line are
offline-tested only. None is wired into your Copilot settings by default.

### Tier 2: `route_size` MCP tool (use only if Tier 1 stops working)

Tier 1 (the `userPromptTransformed` hook) is the normal path. Use Tier 2 only when a Copilot CLI update stops the
rewrite from reaching the model. Tier 2 uses documented features only:

- `sessionStart` hook (`hooks/model-router-session.json`) returns `additionalContext` with a standing rule: call the
  `route_size` tool for each new request that is not a short follow-up, then do what the result says.
- `router_mcp.py` is a stdlib stdio MCP server (JSON-RPC 2.0, one tool). `route_size` runs the same `decide()`/`record()`
  and returns the same routing note as the hook. When the router is OFF it says so and writes nothing.

Install with `./install.sh --tier2`. The installer prints the `mcpServers` snippet; merge it into
`~/.copilot/mcp-config.json` yourself:

```json
{"mcpServers": {"model-router": {"type": "local", "command": "python3",
                               "args": ["-I", "<install dir>/router_mcp.py"], "tools": ["*"]}}}
```

Downsides: the model decides whether to call the tool, and each message costs one extra tool round-trip on the main
model. The standing rule is sent at session start, so it also applies while the router is OFF (the tool then returns
the OFF text). Do not run Tier 1 and Tier 2 together for long: both size each message.

### Tier 3: `routercp` (routes the main model)

`routercp` sizes a prompt with Jev and then runs Copilot CLI on the model Jev picked. This is the one thing Tier 1 cannot
do: it changes the main model, and for `hardest` it adds `--reasoning-effort high`.

```bash
export PATH="$HOME/.copilot/model-router/bin:$PATH"   # or fish_add_path; the installer prints the line
routercp "Research the main options for migrating our reporting from Postgres to ClickHouse."
routercp -i "Should we rewrite billing in-house or buy a vendor?"   # interactive session
```

On Windows `routercp.ps1` does the same from PowerShell (`routercp "prompt"` once the `bin` folder is on PATH; the installer
prints the line). A prompt that starts with `-` needs `-Prompt "..."`.

Mapping: tiny `claude-haiku-5.5`, everyday `claude-sonnet-5.5`, large `claude-opus-5.5` with `--reasoning-effort medium`,
hardest `claude-opus-5.5` with `--reasoning-effort high`. Kept by the main model, or router OFF: plain `copilot` on
your default model. Each `routercp` run starts a new session, so it sizes every prompt as a first request. Inside the
copilot run `MODEL_ROUTER_PRESIZED=1` stops the Tier 1 hook from sizing the same prompt again. Control phrases still
work through the hook. Trade-offs: no mid-conversation switching (`--continue` with another model is unverified); with `-i` the
`MODEL_ROUTER_PRESIZED` variable stays set for the whole interactive session, so later messages in it are not sized by the
Tier 1 hook either (the main model is already the one Jev picked); and the prompt is on argv, which `ps` can show.

### Status line

`router_statusline.py` prints one line from `state.json` and the last entry of `decisions.log`:
`Router ON · large 77%`, `Router ON · kept (unsure)`, `Router ON · no decisions yet`, or `Router OFF`. It reads no message text
and fails open (`Router ?`). The installer prints this snippet; paste it into `~/.copilot/settings.json` yourself:

```json
"statusLine": {"type": "command", "command": "python3 -I \"<install dir>/router_statusline.py\""}
```

On Windows the installer prints the command in PowerShell form, `& "C:\...\python.exe" -I "...\router_statusline.py"`.
Which shell Copilot uses for the status line on Windows is not documented; if the line stays empty there, try the
command without the leading `& ` and the quotes around the interpreter.

It replaces the Claude Code `systemMessage` line ("Router → large (83%)") as a persistent line below the input, not as a
message in the transcript. It shows the last decision. Its placement and refresh timing are documented but not yet checked in a live
Copilot session.

## Limits

- **`python3` must be on your login shell's PATH** (macOS, Linux). The hook runs a bare `python3`. VS Code (terminal or
  Dock launch) and the Copilot CLI resolve your login-shell environment, so this is normally true; if routing is silent,
  put an absolute interpreter path in `~/.copilot/hooks/model-router.json`. On Windows the installer already writes the
  full interpreter path, so a Python upgrade that moves it needs a re-install.
- **Windows is offline-tested only.** The installer, the hook, `routercp.ps1`, the `fcntl` stand-in and the Credential
  Manager read run in CI on `windows-latest`; no live Copilot session has been checked there yet. Copilot CLI runs hooks
  on Windows with PowerShell 7, which must be on PATH.
- **No block.** Copilot hooks cannot swallow a message. A control phrase costs one cheap model turn that echoes
  the status. The status is also in the transcript.
- **No built-in UI line.** Claude Code's "Router → large (83%)" line has no Copilot equivalent. The optional status line
  (see [Fallbacks](#fallbacks-optional)) approximates it.
- **VS Code ignores `additionalContext` from command hooks**, so the note is appended to `transformedPrompt` instead.
- **Fable is not available** on the tested account, so `hardest` runs on Opus 5.5, the same model as `large`.
  The agent file asks for `reasoningEffort: high`, but the CLI reports `medium` for the helper and the key is
  undocumented, so today the two helpers only differ in name, note and stats. Once the account has Fable:
  `python3 -I ~/.copilot/model-router/router_copilot.py model hardest claude-fable-5.1 --effort high`.
- **Hooks are Preview**, and the Copilot CLI updates itself. Re-run the spikes (S1 for the CLI, S6 for VS Code) after
  an update and pin the version you test with.
- **Silent failures.** Copilot does not show hook errors or timeouts. Check `model router status`, `last error`.
- **Time budget.** The hook is killed after 3 seconds. Jev gets 1.5 seconds, and each Keychain read gets 1 second, so a
  slow Keychain can cost a whole message's routing. The Azure backend adds up to three Keychain reads (endpoint,
  deployment, optional API key) when those are not in the environment.
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
bash tests/run.sh          # Windows: pwsh -File tests/run.ps1
```

They cover control phrases, OFF, slash and `!`, secrets, follow-ups, the confidence threshold, each size's note,
timeouts and HTTP errors, the marker guard, bad input, the session bound, and the agent and hook files
(`test_adapter.py`, 18 cases). `test_phase3.py` (23 cases) covers the Tier 2 MCP server over a pipe, the `size` mode and
`routercp` with a stub `copilot`, the status line, and an installer round-trip in a temporary `COPILOT_HOME`.
`test_models.py` (13 cases) covers the `model` command and chat phrase, flags and bad input, `reset`, a broken
`models.json` (hook fails open, `model` reports), `render-agents`, an install-then-change-then-reinstall round
trip on an installed copy, and `models` against a fixture catalog log (grouping, order, newest log, the chat
phrase, the fallback without a catalog). `test_pwsh.py` (8 cases, wherever `pwsh` is on PATH) parses every `.ps1`
file and runs `install.ps1`, `uninstall.ps1` and `routercp.ps1` the way `test_phase3.py` runs their bash twins.
`test_rename.py` (6 cases) covers the old phrases, environment names, state key and note tag, and both installers run over
an install made under the old name. `test_compat.py` (7 cases) covers UTF-8 stdio under an ASCII console, the `key` mode, and, on Windows only, the
`fcntl` stand-in against a second process and a Credential Manager read of a throwaway credential. The bash-only
cases are skipped on Windows. `test_azure.py` (10 cases) covers the Azure Decision-1 backend against the fake server
standing in for a Foundry deployment and a stub `az` on PATH: URL normalisation, backend selection, the owner-only
token cache, `on` warming the token, the hook's fail-open-then-background-refresh path, the near-expiry refresh, the
`api-key` header, `size` waiting for the token, and `status` / `key` naming the backend without printing its values.

End to end, with a real Copilot session (this costs credits, so run it deliberately):

1. Install (`./install.sh`), then start `copilot` and type `model router on`.
2. Send one canned prompt per size:
   - tiny: `What is the HTTP status code for "not found"?`
   - everyday: `Draft a two-sentence thank-you email to a colleague who covered my shift.`
   - large: `Research the main options for migrating our reporting from Postgres to ClickHouse and write a full report with a comparison table.`
   - hardest: `Should we rewrite our billing system in-house or buy a vendor? Give me a strategy and the risks of each.`
3. Find the newest session: `ls -td ~/.copilot/session-state/*/ | head -1`. Its `events.jsonl` holds
   `hook.start` and `hook.end` events for `userPromptTransformed` (`hook.end` shows `success`), and each
   `assistant.message` ends with a `— done by ... (router-<size>)` footer.
4. Check `tail -n 4 ~/.copilot/model-router/decisions.log` for the four routes, and `model router status` for the counts.
5. Changed model: `router_copilot.py model tiny claude-sonnet-5.5 --label "Test"`, send the tiny prompt in a new
   session, and look for `subagent.started` with `"model": "claude-sonnet-5.5"` in `events.jsonl` and
   `— done by Test (router-tiny)` in the reply. Then `model reset`.

Nothing in the tests runs `copilot`. The `events.jsonl` check is manual.

## Layout

```
model-router-copilot/
  README.md  SECURITY.md  LICENSE
  install.sh  uninstall.sh       macOS, Linux
  install.ps1  uninstall.ps1     Windows (PowerShell twins; also run under pwsh elsewhere)
  files/
    router.py                    core, verbatim copy of model-router/files/router.py
    router_copilot.py               adapter: transform hook, on/off/status/reset, model (per-size models), size (routercp), session (Tier 2), key
    router_compat.py                Windows shims loaded by the adapter: fcntl stand-in, Credential Manager key, UTF-8 stdio
    router_mcp.py                   Tier 2 stdio MCP server with route_size (opt-in: install.sh --tier2)
    router_statusline.py            status line printer (snippet only, not registered)
    bin/routercp  bin/routercp.ps1     Tier 3 wrapper: size, then copilot --model <id>
    hooks/model-router.json.tmpl   hook file template (@JR@ = install dir, @PY@ = interpreter command; bash and powershell entries)
    hooks/model-router-session.json.tmpl  Tier 2 sessionStart template
    agents/router-{tiny,everyday,large,hardest}.agent.md.tmpl   helper agent templates (rendered with models.json)
    skills/model-router/SKILL.md   /model-router skill template
  tests/
    run.sh  run.ps1              python3 -m unittest discover -s tests -v
    test_adapter.py              offline tests of the hook and the packaging
    test_phase3.py               Tier 2 MCP, size mode, routercp, status line, installer round-trip
    test_models.py               per-size models, the models listing
    test_pwsh.py                 install.ps1, uninstall.ps1, routercp.ps1 (needs pwsh)
    test_compat.py               UTF-8 stdio, key mode, Windows lock and Credential Manager shims
    test_azure.py                Azure Decision-1 backend: token cache, background refresh, headers, status
    test_rename.py               old jev-router names still work; installer migration
    fake_jev.py                  local stand-in for api.typesafe.ai (query-string controlled)
```

## License

[MIT](LICENSE)
