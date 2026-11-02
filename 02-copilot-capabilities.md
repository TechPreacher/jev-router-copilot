# 02 - GitHub Copilot extension surfaces (as of 2026-10-29)

Research date: 2026-10-29. Sources: docs.github.com and code.visualstudio.com (VS Code pages show a 10/28/2026 date), plus the locally installed **GitHub Copilot CLI 1.0.88** (`copilot --help`, `copilot help config|commands|environment`) and **VS Code 1.144.0** on this Mac.
Legend: **Verified** = stated in official docs or local CLI help. **Unverified** = inferred, third-party, or contradictory - must be tested in a spike.

## A. Copilot CLI (`copilot`)

### A1. Hooks

Source: [CLI hooks reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference), [Hooks configuration](https://docs.github.com/en/copilot/reference/hooks-configuration).

- **Events (verified):** `sessionStart`, `sessionEnd`, `userPromptSubmitted` (alias `UserPromptSubmit`), `userPromptTransformed`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `permissionRequest`, `agentStop` (`Stop`), `subagentStart`, `subagentStop`, `errorOccurred`, `preCompact`, `notification`.
- **Locations (verified):** user `~/.copilot/hooks/*.json` (or `$COPILOT_HOME/hooks/`), repo `.github/hooks/*.json`, inline `hooks` in `~/.copilot/settings.json`, `.github/copilot/settings(.local).json`, repo `.claude/settings(.local).json`, plugin `hooks.json`, policy `/etc/github-copilot/policy.d/*.json`, and **agent frontmatter `hooks:` (CLI only)**. Note: user-level `~/.claude/settings.json` is *not* in the list, so the existing jev-router hook is not picked up by the CLI.
- **File schema (verified):** `{"version":1,"hooks":{"<event>":[{"type":"command","bash":"...","powershell":"...","command":"...","cwd":"...","env":{},"timeoutSec":30}]}}`; `exec`/`args` run without a shell (CLI only). Default timeout 30 s; **timeouts are fail-open** (S4 verified on 1.0.105: timeout, non-zero exit and invalid JSON all fail-open, hook killed, nothing shown to the user, see `spikes/S4-result.md`). Exit 0 -> stdout parsed as JSON; 2 = warning (deny for `preToolUse`/`permissionRequest`); other non-zero -> logged, fail-open (except `preToolUse` fail-closed).
- **Two payload styles (verified):** camelCase (`sessionId`, `timestamp` ms, `cwd`, `prompt`) or VS Code/Claude-compatible snake_case when using the PascalCase alias (`hook_event_name`, `session_id`, ISO `timestamp`, `cwd`, `prompt`). **No `transcript_path` for prompt events** (only `subagentStart` has `transcriptPath`).
- **`userPromptSubmitted` - the critical gap (verified):** the only output field is `modifiedPrompt`, and *"Command and HTTP config-file `userPromptSubmitted` hooks have their output dropped, including `modifiedPrompt`."* Honored only for SDK programmatic hooks. No `additionalContext`, no `decision: block` for command hooks. **=> The Claude Code pattern (UserPromptSubmit + additionalContext / block) does not port as-is.**
- **`userPromptTransformed` - the likely injection point (partly verified):** fires after the runtime turns the prompt into model-facing content and before it is saved. Input: `sessionId`, `timestamp`, `cwd`, `prompt`, `transformedPrompt`. Output: `modifiedTransformedPrompt` (replaces model-facing content and session history; the visible timeline prompt is unchanged; replayed on resume). Mutation-only, cannot block. The event table says it is processed with **no command-hook exception**, but the docs never explicitly say "command hooks honored" -> **unverified, spike first.**
- **`sessionStart`** (verified): command hooks may return `additionalContext` ("Only `additionalContext` is consumed for `sessionStart` (command and HTTP variants)"). Input includes `source` (`startup|resume|new`) and optional `initialPrompt`.
- **`subagentStart`** (verified): `additionalContext` is prepended to the subagent's first user message; matcher = regex on `agentName`. Cannot block.
- **`postToolUse`** returns `additionalContext` / `modifiedResult` (command-hook support for `additionalContext` implied, not explicit).
- **`prompt`-type hooks**: only on `sessionStart` (auto-submits text for new interactive sessions).
- Third-party gist (2026-03-10) reported `additionalContext` being ignored by the CLI runtime for prompt hooks while `modifiedPrompt` worked (SDK) - consistent with the docs above. Unverified whether since changed.

### A2. Custom agents and subagents

Sources: [Create custom agents for CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli), [Custom agents configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration), [About custom agents](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents).

- **Locations (verified):** `~/.copilot/agents/` (user), `.github/agents/` (repo), repo `.claude/agents/` also read, plus plugins and org agents. File `<id>.agent.md` (or `.md`); ID = filename without extension; subdirs become `dir--name`.
- **Frontmatter (verified):** `description` (required), `name`, `tools` (default all; aliases `execute|read|edit|search|agent|web|todo`, Claude names like `Bash`, `Task` accepted), `model`, `model-policy: required` (make the model mandatory, not a preference), `reasoningEffort` (listed in the earlier research but absent from the current reference pages and from `copilot help config`; the live run shows it ignored, helper runs at `medium`), `include-custom-instructions` (default false), `strict-tools-list`, `mcp-servers`, `hooks`, `user-invocable`, `disable-model-invocation` (`infer` retired). Body up to 30,000 chars.
- **Per-agent model (verified):** "Subagents can use their own configured model"; unset -> inherits parent. Additionally CLI config `subagents.agents.<agent-name>` sets per-subagent `model`, `effortLevel`, `contextTier` (`/subagents` command) - from `copilot help config`.
- **Delegation (verified):** the main agent delegates automatically by description, or when told "Use the X agent to ...", via its native **`task`** tool; subagents get their own context window; visible in `/tasks`. Also `/agent <name>`, `copilot --agent <name>`.
- **Model ID strings (partly verified):** the local CLI 1.0.88 `copilot help config` lists `claude-sonnet-5`, `claude-fable-5.1`, `claude-fable-5`, `claude-opus-5`, `claude-opus-4.8`, `claude-haiku-4.5`, `gpt-6-astra`, `gpt-5.6-sol|terra|luna`, `gpt-5.5`, `gpt-5.4-mini`, `gpt-5-mini`, `gemini-3.8-flash`, `grok-4.5`, `kimi-k3`, ... It does **not** yet list the 5.5 Claude models. The [supported models page](https://docs.github.com/en/copilot/reference/ai-models/supported-models) lists Claude Haiku 5.5, Sonnet 5.5, Opus 5.5 and Fable 5.1 as GA, and the [2026-09-28 changelog](https://github.blog/changelog/2026-09-28-claude-sonnet-5-5-in-github-copilot) says Sonnet 5.5 is in the CLI picker. A third-party page gives `claude-sonnet-5.5`. => **S3 (CLI 1.0.105, 2026-10-29) verified** `claude-haiku-5.5`, `claude-sonnet-5.5`, `claude-opus-5.5` and `claude-haiku-4.5` via `--model`. `claude-fable-5.1` is a schema-valid ID but is **rejected** ("is not available") because it is absent from this account's CAPI model catalog. See `spikes/S3-result.md` for the full 41-model catalog.

### A3. Model selection

- `--model <model>` ("use 'auto' to let Copilot pick automatically"), `COPILOT_MODEL` env, `model` in `~/.copilot/settings.json`, `/model` (session), `/config model` (user default) - all verified locally.
- **Copilot has its own router:** model `auto` + `autoTier` = `efficiency|balance|intelligence|fast` (`--auto-tier`, `COPILOT_AUTO_TIER`). This competes with / overlaps jev-router's purpose.
- No documented way for a hook to change the main session model mid-session.

### A4. Other surfaces

- Instructions: `~/.copilot/copilot-instructions.md`, `~/.copilot/instructions/*.instructions.md`, repo `.github/copilot-instructions.md`, `AGENTS.md`; `/instructions` toggles them. `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`.
- Skills: `~/.copilot/skills/<name>/SKILL.md` (invokable as `/<skill>`); `/skills`.
- MCP: `~/.copilot/mcp-config.json`.
- Plugins ([plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)): `plugin.json` + `agents/`, `skills/`, `hooks.json`, `.mcp.json`; install with `copilot plugin install ./path | OWNER/REPO[:PATH] | git-url`. v1.0.76 (2026-07-29) added hook enable/disable in `/plugins`.
- `!` shell escape in the interactive CLI: **unverified** from docs in this research (commonly available); the router skips `!` prompts anyway.
- **Copilot SDK** ([SDK hooks](https://docs.github.com/en/copilot/how-tos/copilot-sdk/hooks/user-prompt-submitted)): TS/Python/Go/.NET/Java. Programmatic `onUserPromptSubmitted` / `on_user_prompt_submitted` may return `modifiedPrompt`, `additionalContext`, `suppressOutput`, `decision: "block"` + `reason`. Model is set per session at `create_session`; no documented per-message `setModel` (unverified).

## B. GitHub Copilot in VS Code

### B1. Harnesses (new in 2026 - this decides everything)

Source: [Choose an agent harness](https://code.visualstudio.com/docs/agents/run/agent-harnesses), [Migrate customizations](https://code.visualstudio.com/docs/agent-customization/migrate-customizations).

| Harness | What | Hooks | Subagent tool | Model field |
|---|---|---|---|---|
| **Copilot** (recommended default) | Copilot SDK in the Agent Host (same runtime as the CLI) | Shared Copilot hook files (`~/.copilot/hooks`, `.github/hooks`, ...) | native `task` | string or preference array |
| **Local** (legacy) | VS Code's built-in extension-host agent | Legacy Local hooks (`chat.useHooks`; Claude files need `chat.useClaudeHooks`) | `runSubagent` (`agent/runSubagent`) | name or array, qualified `Model Name (vendor)` |
| **Claude** | Anthropic Claude Agent SDK in VS Code; billed via Copilot or own key | "Claude project configuration" - VS Code release notes say `~/.claude/settings.json` hooks and `~/.claude/agents` are read (**unverified for this harness**) | Claude `Agent` tool | Claude aliases |
| **Codex** | OpenAI Codex | n/a | n/a | n/a |

Harness is chosen per session via **Session Target**, before the first prompt; Claude/Codex are disabled under enterprise-managed Copilot settings.

### B2. Hooks in VS Code

Sources: [Configure agent hooks (Preview)](https://code.visualstudio.com/docs/copilot/customization/hooks), [Legacy Local hooks reference](https://code.visualstudio.com/docs/agents/reference/hooks-reference).

- **Copilot harness (verified):** same files as the CLI (`~/.copilot/hooks/`, `.github/hooks/*.json`, `~/.copilot/settings.json`, `.claude/settings(.local).json`, agent `hooks`, plugins). Statement: *"command-hook output is ignored for `userPromptSubmitted`."* Hooks are **Preview**. Whether `userPromptTransformed` fires in the VS Code Copilot harness: **unverified** (page lists a subset and defers to the GitHub reference; same runtime suggests yes).
- **Local harness (verified, legacy):** events `PreToolUse, PostToolUse, UserPromptSubmit, SessionStart, Stop, SubagentStart, SubagentStop, PreCompact`. `UserPromptSubmit` supports only the common output (`continue`, `stopReason`, `systemMessage`) - **no additionalContext**. `SessionStart` accepts `hookSpecificOutput.additionalContext`. Exit 2 = blocking error, stderr to model.

### B3. Custom agents and subagents in VS Code

Sources: [Custom agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents), [Custom agent file reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference), [Subagents](https://code.visualstudio.com/docs/copilot/agents/subagents).

- **Locations (verified):** `.github/agents/*.agent.md`, `~/.copilot/agents/`, plus Claude format in `.claude/agents/` and `~/.claude/agents/`; Local harness user agents live in VS Code profile storage; `chat.agentFilesLocations` adds paths.
- **Frontmatter (verified):** `name`, `description`, `tools` (`agent` tool set needed for delegation), `model` (string or **array in preference order, first available wins**), `agents` (Local: allowed subagents), `user-invocable: false` (hide from picker, still usable as subagent), `disable-model-invocation`, `handoffs` (Local only; `label/agent/prompt/send/model`), `hooks`, `target` (`vscode`|`github-copilot`).
- **Model naming:** Local uses qualified names `Model Name (vendor)`, e.g. `'Claude Sonnet 4.5 (copilot)'` ([v1.109 notes](https://code.visualstudio.com/updates/v1_109)). Copilot harness: "model IDs available in your harness" - presumably the CLI IDs (**unverified**).
- **Subagent model precedence (Local, verified):** (1) explicit `model` passed to `runSubagent`, (2) custom agent `model`, (3) Auto if `chat.subagents.defaultToAuto`, (4) main model. Nesting via `chat.subagents.allowInvocationsFromSubagents` (max depth 5).
- **Prompt files** (`*.prompt.md`) are Local-only; Copilot harness uses skills instead.

### B4. Extension APIs (fallback)

- [Language Model API](https://code.visualstudio.com/api/extension-guides/ai/language-model) (verified): `vscode.lm.selectChatModels({vendor, family, id, version})`, `model.sendRequest(...)`; needs user consent; can pick any Copilot model per request.
- **Chat participant guide is marked deprecated** in the docs navigation; VS Code recommends agent plugins/tools instead. A `@jev` participant would also lose the agent's tool loop. Not recommended.
- [Agent plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins) bundle agents/skills/hooks/MCP and work across Copilot clients (CLI+VS Code coverage per plugin format: partly verified).

## C. Model mapping (tiny / everyday / large / hardest)

| Size | Claude Code (today) | Copilot CLI ID | VS Code Local name | Non-Anthropic alternative |
|---|---|---|---|---|
| tiny | haiku -> Haiku 5.5 | `claude-haiku-5.5` (verified S3) | `Claude Haiku 5.5 (copilot)` (unverified) | `gpt-5.4-mini` / `gpt-5-mini` |
| everyday | sonnet -> Sonnet 5.5 | `claude-sonnet-5.5` (verified S3) | `Claude Sonnet 5.5 (copilot)` | `gpt-5.5` |
| large | opus -> Opus 5.5 | `claude-opus-5.5` (verified S3) | `Claude Opus 5.5 (copilot)` | `gpt-5.6-sol` |
| hardest | fable -> Fable 5.1 | `claude-fable-5.1` valid ID but **not available on this account** (S3); use `claude-opus-5.5` | `Claude Fable 5.1 (copilot)` | `gpt-6-astra` |

Premium-request multipliers per model were not retrieved (see "Models and pricing for GitHub Copilot"); under Copilot billing the cost trade-off differs from Anthropic token pricing, so re-evaluate whether routing pays off.

## D. Capability matrix vs. jev-router needs

| jev-router needs | Claude Code | Copilot CLI | VS Code - Copilot harness | VS Code - Local | VS Code - Claude harness |
|---|---|---|---|---|---|
| Run code on every prompt | yes | yes (`userPromptSubmitted`, `userPromptTransformed`) | yes | yes | likely (unverified) |
| Inject per-prompt context | `additionalContext` | **no** via `userPromptSubmitted`; **probably** via `userPromptTransformed` rewrite (unverified) | same as CLI (unverified) | **no** | likely, as Claude Code |
| Block prompt / in-chat control phrase | `decision: block` | **no** (command hooks) | **no** | `continue:false` + `stopReason` (unverified for this event) | likely |
| UI notice line | `systemMessage` | no equivalent found | no | `systemMessage` | likely |
| Session-level context | SessionStart | `sessionStart.additionalContext` | yes | `SessionStart` | yes |
| Model-pinned helper agents | `model:` alias | `model:` + `model-policy: required`, or `subagents.agents.<n>.model` | `model:` (array) | `model:` / `runSubagent(model)` | `model:` alias |
| Delegation tool | Agent | `task` | `task` | `runSubagent` | Agent |
| Switch main model per message | no | no (only `--model` per process / `/model`) | no | no | no |
| Built-in alternative | - | `--model auto` + `autoTier` | Auto model | Auto | - |
