# Live end-to-end in VS Code Copilot harness (VS Code 1.144.0, 2026-10-30)

Four prompts, identical to the CLI run (E2E-cli-result.md), sent with `code chat -r -m agent "<prompt>"` in the
window `~/Temp/jev-router-github-copilot`. Router ON before the first send, OFF after the last. Raw events in `e2e-vscode-raw/`.

## Verdict: PASS. All four sizes routed to the right helper on the right model, and the footer was relayed.

| # | Prompt (words) | Jev (decisions.log) | Note in transformed prompt | Helper / model (subagent events) | Footer relayed | Wall (user.message to last turn_end) | Session |
|---|---|---|---|---|---|---|---|
| 1 | Capital of Portugal? One word. (8) | tiny p=1.00 | yes | jev-tiny / claude-haiku-5.5 | "— done by Claude Haiku 5.5 (jev-tiny)" | 9 s | 45b48b42-accf-4bf7-96e6-e2416a9cd972 |
| 2 | Friendly reschedule email (19) | everyday p=0.93 | yes | jev-everyday / claude-sonnet-5.5 | "— done by Claude Sonnet 5.5 (jev-everyday)" | 11 s | 3e42345e-c744-4076-ba1d-8e422a6d345f |
| 3 | Rails monolith to Kubernetes plan (23) | large p=0.77 | yes | jev-large / claude-opus-5.5 | "— done by Claude Opus 5.5 (jev-large)" | 117 s | 0d1b72ae-045d-488b-92e4-83a25c37689c |
| 4 | B2C to B2B pivot strategy (30) | hardest p=0.85 | yes | jev-hardest / claude-opus-5.5 | "— done by Claude Opus 5.5 (jev-hardest)" | 50 s | 5f97e3ea-e90f-4307-b7bb-3db96ea7c854 |

Main model was `gpt-6.1-sol` in every session. Each helper reported `reasoningEffort: medium` (same as the CLI run,
so `reasoningEffort: high` in the agent files is still ignored). Helper token totals: tiny 49015, everyday 49243,
large 106321, hardest 51348.

## Findings

1. **Hook works in VS Code.** `userPromptTransformed` `hook.end` is `success: true` with `modifiedTransformedPrompt`
   containing the `[jev-router]` note for all four main prompts. The main model then called the `task` tool with the
   matching `agent_type`, and the helper's footer came back through the main reply.
2. **Nested hook fires, no recursion.** Each helper's own `userPromptTransformed` fired (it carries `parentToolCallId`),
   and none of those returned a note (0 of 4). The early return from the CLI fix holds in VS Code.
3. **python3 on PATH: yes for this launch path.** VS Code was started with `code` from this terminal, so it inherited
   the shell PATH (`~/.pyenv/shims/python3`, Python 3.12). The Dock-launch case was NOT tested. The hook command is a bare
   `python3`, and `launchctl getenv PATH` returned nothing here. `/usr/bin/python3` is 3.9.6, so a Dock launch would
   pick a different interpreter. Open: quit VS Code, launch from the Dock, and rerun prompt 1 to confirm.
4. **Session reuse: no reuse.** Each `code chat -r -m agent` created a new sessionId (5 sends, 5 new session dirs).
   So prompt 1 ran in a fresh session and the "12 words or fewer after history" rule was not hit. No 13+ word
   re-send was needed.
5. **Accidental extra prompt (my mistake).** A stray `| head -0` on a test invocation ran my send script with the
   placeholder prompt `x`. This was a real Copilot turn: session e9f9eeac-32b8-4d24-b533-68479b388a52, routed tiny p=0.93
   (decisions.log line 13:10:57), and it ran a helper. It is not part of the four-prompt verdict. Raw file:
   `e2e-vscode-raw/extra-accidental-x.events.jsonl`.
6. **Poll false positive (my harness, not the product).** My first poll marked prompts 3 and 4 done about 30 s in,
   before the helpers finished. Walls above are re-measured from event timestamps to the last `assistant.turn_end`.
7. Walls are longer than the CLI run for prompt 3 (117 s vs 101 s) and shorter for prompts 1, 2 and 4.

## Router state

Router OFF (`jev_copilot.py status`: OFF). Jev totals after the run: 12 calls, 5472 input tokens, $0.000230.
Decisions added: 5 lines (the four prompts plus the accidental `x`), listed in `e2e-vscode-raw/decisions.log.new`.

## Raw files (`~/Temp/jev-router-github-copilot/spikes/e2e-vscode-raw/`)

- `1-tiny.events.jsonl`
- `2-everyday.events.jsonl`
- `3-large.events.jsonl`
- `4-hardest.events.jsonl`
- `extra-accidental-x.events.jsonl` (the stray `x` prompt, see finding 5)
- `decisions.log.new` (5 new decision lines)

## Dock-launch follow-up (2026-10-30, same VS Code 1.144.0)

Procedure: `osascript -e 'quit app "Visual Studio Code"'`, then `open -a "Visual Studio Code" ~/Temp/jev-router-github-copilot`
(LaunchServices launch, parent pid 1 = launchd, same path as a Dock click; `open` does not forward the caller's shell
environment). Router ON, prompt 1 re-sent with `code chat -r -m agent`, router OFF.

Verdict: **PASS**. Session 1a0bd87e-703b-4b9c-b855-9d29bb265527: `userPromptTransformed` hook.end success with the
`[jev-router]` note, decisions.log `tiny p=1.00`, `subagent.started` jev-tiny / claude-haiku-5.5, footer
"— done by Claude Haiku 5.5 (jev-tiny)", 7 s wall. Nested hook for the helper fired and stayed silent.

Why it works: VS Code resolves the user's login-shell environment at startup on macOS and applies it to its own process
(`ps eww` on the main `Code` process showed the full shell PATH incl. `~/.pyenv/shims`, with `launchctl getenv PATH`
empty), so hooks see the same `python3` as a terminal launch (here pyenv 3.12.16). The earlier concern about `/usr/bin/python3`
3.9.6 is moot on this machine. Edge that remains theoretical: a user whose login shell does not put a `python3` on PATH.

Raw: `e2e-vscode-raw/dock-1-tiny.events.jsonl`, `e2e-vscode-raw/decisions.log.dock`.

> Raw captures removed before publishing (2026-11-02): Copilot `events.jsonl` session files and Copilot debug logs, because they contain GitHub's system prompts, account usage records, device policy and local paths. The evidence quoted above was taken from them; the remaining files in the raw folder are the scripts and small outputs.
