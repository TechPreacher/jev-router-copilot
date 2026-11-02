# Live test: Tier 1 reinstall + `jevcp` (Copilot CLI 1.0.105, 2026-11-02)

## Verdict: PASS

## Reinstall (`./install.sh`, no flags)

- Exit 0, self-test passed. Installed files byte-identical to source (`cmp`): `jev-router/{router.py, jev_copilot.py,
  jev_statusline.py, bin/jevcp}`. Hook and agent files were already current and were not rewritten.
- One backup: `~/.copilot/jev-router/jev_copilot.py.bak-20261102-073244` (the Phase 1 adapter).
- `state.json` preserved (stats since 2026-10-30 10:00, 13 Jev calls before this run). `settings.json` and
  `mcp-config.json` untouched (mtimes Oct 12). Other hooks untouched. No Tier 2 session hook installed.
- Status line smoke: `printf '{}' | python3 -I ~/.copilot/jev-router/jev_statusline.py` -> `Jev OFF`.

## jevcp run (router ON for one prompt, OFF right after)

| Prompt | Jev | stderr | Session model | Hook re-sized? | Subagent? | Wall | Credits |
|---|---|---|---|---|---|---|---|
| Friendly two-sentence email, move Thursday sync to Friday morning (99 chars) | everyday p=0.87 | `jevcp: everyday -> claude-sonnet-5.5` | claude-sonnet-5.5 (`session.start` and `assistant.message`) | no | none | 20 s | 8.75 AI credits (CLI footer) |

Evidence (`jevcp-raw/jevcp.events.jsonl`, session fd13d5d7-dde9-4a78-b16f-d5d9a39a614b):
- `decisions.log` gained exactly one line (the `size` call); the hook did not size the prompt again.
- The `userPromptTransformed` `hook.end` event has keys `hookInvocationId, hookType, success` and **no `output` key**.
  In every earlier Tier 1 session (e.g. `e2e-vscode-raw/dock-1-tiny.events.jsonl`) the same event carries
  `output.modifiedTransformedPrompt` with the note. So `JEV_ROUTER_PRESIZED=1` was inherited by the hook and the note
  was not injected. Conclusive, not inferred.
- No `subagent.started`: jevcp routes the **main** model, which Tier 1 cannot do.
- Reply head: "**Subject: Moving Thursday's sync to Friday morning?**".

## Observations

- Cost signal for Phase 4: one everyday prompt on Sonnet 5.5 as the main model cost 8.75 AI credits (34.6k tokens
  written, mostly the CLI's own context). Tier 1 helper runs put the same work on a subagent; compare per prompt
  before deciding which tier is cheaper.
- Still not live-tested: Tier 2 (`jev_mcp.py` + sessionStart rule), the status line inside a real CLI session
  (only the script output was checked), `jevcp -i`, and `--continue` with a different model.

## Raw

`spikes/jevcp-raw/`: install.log, jevcp.stdout, jevcp.stderr, jevcp.timing, jevcp.events.jsonl, pre-session.txt.

> Raw captures removed before publishing (2026-11-02): Copilot `events.jsonl` session files and Copilot debug logs, because they contain GitHub's system prompts, account usage records, device policy and local paths. The evidence quoted above was taken from them; the remaining files in the raw folder are the scripts and small outputs.
