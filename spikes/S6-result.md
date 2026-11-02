# Spike S6 result: VS Code Copilot harness and `~/.copilot/hooks` (2026-10-29)

Environment: VS Code 1.144.0, built-in Copilot 0.72.0, default (Copilot) harness. Temporary hook file
`~/.copilot/hooks/zz-s6-spike.json` registered `s6_submitted.sh` on `userPromptSubmitted` (prints
`{"additionalContext":"End your answer with the word MANGO."}`) and `s6_transformed.sh` on `userPromptTransformed`
(prints `modifiedTransformedPrompt` = transformedPrompt + "...end your answer with the single word BANANA"). Prompt sent
with `code chat -r -m agent "What is the capital of France? Answer in one short sentence."`; `-r` reused the open window,
whose workspace was `~/Code/GitHub Enterprise/Microsoft/fde-energy-studio`, so the chat lives there. Hook file removed.
Raw scripts, stdin dumps and `fired.log` in `s6-raw/` (the 11:07:45 line with payload `x` is a local script self-test,
not VS Code).

## Verdict: PASS (reply check done via the shared session store)

The reply was found in `~/.copilot/session-state/d37625a8-79ee-4491-bd1c-bc3010994e4c/events.jsonl` (the VS Code
Copilot harness and the CLI share `~/.copilot/session-state/` and show up in each other's session lists):
`assistant.message.content = "Paris is the capital of France — BANANA"`, `model = gpt-6.1-sol`. The `hook.end` event for
`userPromptTransformed` logs `success` with the `modifiedTransformedPrompt` output. So the rewrite reached the model.

Nuance from `events.jsonl`: the `hook.end` for `userPromptSubmitted` shows `additionalContext` = the `<workspace_info>`
block, i.e. VS Code's own built-in (programmatic) prompt hook. That context did reach the model, while our command hook's
MANGO `additionalContext` on the same event did not. So `additionalContext` on `userPromptSubmitted` is honoured for
programmatic/SDK hooks and dropped for command hooks, exactly as the docs state; the CLI's S1 behaviour is the outlier.
`user.message.transformedContent` (2427 chars) contains BANANA and no MANGO, confirming the stored prompt is the rewritten one.

Original table (before the reply check):

| Event | Fired | stdin keys | Output honoured |
|---|---|---|---|
| `userPromptSubmitted` | yes, 11:07:32 | `cwd`, `prompt`, `sessionId`, `timestamp` (camelCase, no `hook_event_name`) | **no**: MANGO text is absent from the following `transformedPrompt`. On CLI 1.0.105 (S1) the same hook's `additionalContext` was chained in as a `<system_reminder>`; the VS Code harness drops it, matching the docs. |
| `userPromptTransformed` | yes, 11:07:32 | same + `transformedPrompt` (string, 2370 chars) | **yes**: reply `Paris is the capital of France — BANANA` in `session-state/<id>/events.jsonl` (not in `~/.copilot/logs`, `GitHub Copilot Chat.log` or workspaceStorage). |

`transformedPrompt` shape in VS Code: `<current_datetime>...</current_datetime>` + prompt + a `<system_reminder>` holding
`<workspace_info>` (workspace tree). No `additionalContext` block from the submitted hook.

## Consequences for the plan

1. **Tier 1 must use `userPromptTransformed` + `modifiedTransformedPrompt`** to work in both the CLI and VS Code. The
   `userPromptSubmitted.additionalContext` path only works on the CLI (and is undocumented there), so treat it as a
   bonus, not the primary mechanism. The adapter should emit on `userPromptTransformed` only; keep the idempotency guard.
2. One `~/.copilot` install does reach VS Code: the hook file, the events and the payload shape are identical to the
   CLI. The S1 and S4 findings (fail-open, no user-visible warning, no `transcript_path`) presumably carry over;
   fail-open in VS Code is unverified.
3. `transformedPrompt` in VS Code already carries a sizeable `<workspace_info>` block. The routing note must be appended
   after it, not inserted before, and `decide()` must size the original `prompt`, not `transformedPrompt`.
4. **Path B is confirmed as the product**: one `~/.copilot` install (hook on `userPromptTransformed` + agents) serves
   both the CLI and VS Code. Path C is only for the legacy Local harness.
5. For end-to-end tests, read replies and `hook.start`/`hook.end` events from
   `~/.copilot/session-state/<sessionId>/events.jsonl`; the `sessionId` comes from the hook payload.

> Raw captures removed before publishing (2026-11-02): Copilot `events.jsonl` session files and Copilot debug logs, because they contain GitHub's system prompts, account usage records, device policy and local paths. The evidence quoted above was taken from them; the remaining files in the raw folder are the scripts and small outputs.
