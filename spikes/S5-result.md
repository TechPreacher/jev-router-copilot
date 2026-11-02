# Spike S5 result: existing jev_router under the VS Code Claude harness (2026-10-29)

Environment: VS Code 1.144.0, built-in Copilot extension 0.72.0 (no separate github.copilot-chat), `anthropic.claude-code`
installed. jev_router installed and ON in `~/.claude/settings.json` (UserPromptSubmit, third entry, `python3 -I
"$HOME/.claude/jev-router/router.py" hook`, timeout 3).

## Verdict: UNVERIFIED (no runtime test possible without the GUI; no settings were edited)

Why no automated test:
- The harness (Local / Copilot / Claude / Codex) is chosen per session through the **Session Target** control in the chat
  view. `code chat --help` offers `-m <ask|edit|agent|custom-mode-id>`, `-a`, `-r`, `-n`, `--profile`, `--maximize` but no
  harness flag. A CLI-sent prompt lands in the default harness (Copilot), which does not test the Claude harness.
- Switching the default through settings was out of scope (read-only on config).

Evidence collected:
- `chat.hookFilesLocations` in the user settings already lists `~/.claude/settings.json` (and `~/.copilot/hooks`,
  `.claude/settings*.json`, `~/.agents/hooks`). The hooks doc says that *sharing a hook file location does not
  establish runtime compatibility* and that the Copilot harness only maps its own event names (`userPromptSubmitted`),
  so the Claude-style `UserPromptSubmit` entry is not picked up by the Copilot harness.
- Docs (https://code.visualstudio.com/docs/copilot/customization/hooks): "Other session targets use their own hook
  implementations" (Claude, Codex). Which `~/.claude` files the Claude harness reads is not stated.
- Docs (https://code.visualstudio.com/docs/copilot/agents/third-party-agents): Claude support on by default unless
  enterprise-managed settings disable it (`chat.agentHost.claudeAgent.enabled`); "Sessions use Claude project
  configuration"; "Harness-specific customizations, including hooks, follow the selected harness."
- Claude Agent SDK docs: filesystem hooks from `settings.json` load only when the matching `settingSources` entry
  (`user` for `~/.claude/settings.json`) is passed by the host. Whether VS Code passes `user` is unverified.
- `decisions.log` has four `self_error` lines on 2026-10-28 13:58-14:03 (`RuntimeError: TYPESAFE_API_KEY not set`),
  seven minutes before the Keychain commit `b412240`. Consistent with a GUI-launched host lacking shell env, but the log
  has no source field, so this is not proof of a VS Code origin.
- `chat.useClaudeHooks` exists for the legacy Local harness; its effect on the Claude target is unverified.

## Manual probe (about 2 minutes)

1. `wc -l ~/.claude/jev-router/decisions.log` (baseline).
2. In VS Code, open Chat, click the **Session Target** control, choose **Claude**.
3. Send exactly: `jev spike S5 probe` (18 characters).
4. After about 60 s: `tail -2 ~/.claude/jev-router/decisions.log` and `cat ~/.claude/jev-router/state.json`.
5. PASS = a new line stamped now with `"chars": 18` (a route or a `self_error`; either proves the hook fired).
   FAIL = no new line.
6. If it fired, also send `jev router status`. If the chat shows the status text without a model reply, `decision: block`
   and `systemMessage` are honoured too.

## Consequences for the plan

Path A (zero-port via the Claude harness) stays a bonus, not the product. Path B (shared `~/.copilot` install, Copilot
harness) is the one to build and test (S6). If the manual probe passes, document Path A in the original README later.
