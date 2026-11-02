# Spike S1 result: Copilot CLI prompt hooks (2026-10-29)

Environment: GitHub Copilot CLI 1.0.88-1, macOS, model `gpt-6.1-sol` (admin-managed). Temporary hook file
`~/.copilot/hooks/zz-s1-spike.json` registered command hooks on `userPromptSubmitted` and
`userPromptTransformed`; removed after the test. Two `copilot -p ... --allow-all-tools` runs.
Raw stdin dumps and hook scripts are next to this file.

## Verdict: PASS. Tier 1 is viable.

| Event | Fired | stdin top-level keys | Output honoured |
|---|---|---|---|
| `userPromptSubmitted` | yes | `cwd`, `prompt`, `sessionId`, `timestamp` | **yes** (contrary to docs): `modifiedPrompt` replaced the prompt; `additionalContext` was wrapped in a `<system_reminder>` block and appended to the model-facing prompt |
| `userPromptTransformed` | yes | `cwd`, `prompt`, `sessionId`, `timestamp`, `transformedPrompt` (string) | **yes**: `modifiedTransformedPrompt` replaced the model-facing content; run 2 reply ended with the injected word |

Evidence (log `~/.copilot/logs/process-1793263899845-82588.log`):
- L605 `[rust:hooks] [hook stdout] {"modifiedPrompt": ..., "additionalContext": ...}`
- L616 `[rust:hooks] [hook stdout] {"modifiedTransformedPrompt": "<current_datetime>...</current_datetime>\n\n<prompt>\n\n...MANGO...\n\n<system_reminder>\n...\n</system_reminder>\n\nIMPORTANT: end your answer with the single word BANANA."}`
- L676 model request contains the BANANA suffix; run 2 reply verbatim: `The capital of France is Paris — BANANA`.
- Run 1 ("Reply with exactly: hello") answered `hello`; model obeyed "exactly" over the suffix, so the reply alone is not proof, but the request log is.

Payload shape notes:
- camelCase keys; `timestamp` in ms; no `transcript_path` (confirms the follow-up-detection gap).
- `transformedPrompt` = `<current_datetime>...</current_datetime>` + prompt (+ any `userPromptSubmitted` edits). Session IDs: `8bf14867-...`, `019c6783-...`.
- No hook errors or parse failures logged. Fail-open not exercised (S4 still open).

## Consequences for the plan

1. **Use `userPromptSubmitted` + `additionalContext` as Tier 1**, not `userPromptTransformed`. It behaves like Claude Code's `UserPromptSubmit`: the note lands in a `<system_reminder>` block and the adapter does not need to re-emit `transformedPrompt`. Keep `userPromptTransformed` as Tier 1b since the docs say submitted output is dropped; this build honours it, a future build may not. The adapter can emit both (`additionalContext` on submitted, `modifiedTransformedPrompt` on transformed) with the idempotency guard preventing a double note.
2. Still no `decision: block`: not tested here (unverified). On/off/status still needs the "echo this status" rewrite or the `/jev-router` skill.
3. Docs vs behaviour drift is real. Pin the CLI version in the README and re-run this spike after `copilot update`.

Not tested: `--resume` replay, `decision: block`, fail-open on timeout (S4), VS Code Copilot harness (S6).
