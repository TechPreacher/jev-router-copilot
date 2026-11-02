# Live test: changed per-size model in a real Copilot CLI session (1.0.105, 2026-11-02)

## Verdict: PASS

Real `~/.copilot`, reinstalled the same morning (adapter with `model` command). One paid session.

## Procedure

1. `jev_copilot.py model tiny claude-sonnet-5.5 --label "Sonnet Tiny Test"` -> `models.json` written, `agents/jev-tiny.agent.md`
   re-rendered (`model: claude-sonnet-5.5`, footer `— done by Sonnet Tiny Test (jev-tiny)`).
2. `jev router on`, then `copilot -p "Capital of Portugal, one word" --allow-all-tools` from the output folder.
3. `jev router off`, `jev_copilot.py model reset`.

## Result

| Prompt | Jev | Main model | Helper | Footer | Wall | Credits |
|---|---|---|---|---|---|---|
| Capital of Portugal, one word (29 chars) | tiny p=1.00 | gpt-6.1-sol (admin-managed) | jev-tiny / **claude-sonnet-5.5** | "— done by Sonnet Tiny Test (jev-tiny)" | 28 s | 13.36 AI credits |

Evidence (`model-live-raw/copilot.events.jsonl`, session 5b8a648d-6dd9-47dc-ac4e-9bf661876be2):
- First `userPromptTransformed` `hook.end` carries `output.modifiedTransformedPrompt` with the `[jev-router] ... TINY (p=1.00)` note.
- `subagent.started` / `subagent.completed`: agentName `jev-tiny`, model `claude-sonnet-5.5` (was `claude-haiku-5.5` in every
  earlier tiny session). The helper's `assistant.message` has `model: claude-sonnet-5.5` and the test label in the footer.
- Second `hook.end` (the helper's own prompt) has no `output` key: nested-hook guard worked.
- `decisions.log` gained exactly one line (`tiny p=1.0`, 394 tokens, 275 ms).
- CLI stdout: `● Jev-tiny (model: claude-sonnet-5.5)`, reply "Lisbon".

After `model reset`: `models.json` removed, 4 agent files re-rendered, `jev-tiny.agent.md` back to `model: claude-haiku-5.5`
and the default footer. Router OFF. Source repo clean.

## Observations

- A changed model takes effect for the next session with no reinstall and no checkout: the installed adapter rewrites the agent file.
- Cost: 13.36 credits for one tiny prompt (72.9k tokens written, 52.1k uncached) because the main session is gpt-6.1-sol and the
  helper ran on Sonnet instead of Haiku. The previous haiku tiny run was cheaper; the helper model drives the bill.
- Not tested: `--effort` (only `jevcp` uses it), `--policy preferred`, a model ID the account is not entitled to.

## Raw

`spikes/model-live-raw/`: pre-session.txt, copilot.stdout, copilot.stderr, copilot.timing, copilot.events.jsonl, off.txt.

> Raw captures removed before publishing (2026-11-02): Copilot `events.jsonl` session files and Copilot debug logs, because they contain GitHub's system prompts, account usage records, device policy and local paths. The evidence quoted above was taken from them; the remaining files in the raw folder are the scripts and small outputs.
