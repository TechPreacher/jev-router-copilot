# Live end-to-end on the real `~/.copilot` (Copilot CLI 1.0.105, 2026-10-30)

`bash install.sh` into the real `~/.copilot` (no override), `jev router on`, four prompts via `copilot -p ... --allow-all-tools`,
then `off`. The router is still installed and OFF. Pre-existing hooks untouched. Raw outputs in `e2e-raw/`.

## Verdict: PASS. All four sizes routed to the right helper on the right model.

| # | Prompt | Jev (decisions.log) | Note injected | Helper / model (events + usage table) | Footer relayed | Wall |
|---|---|---|---|---|---|---|
| 1 | Capital of Portugal, one word | tiny p=1.00 | yes | jev-tiny / claude-haiku-5.5 | "— done by Claude Haiku 5.5 (jev-tiny)" | 44 s |
| 2 | Friendly reschedule email | everyday p=0.94 | yes | jev-everyday / claude-sonnet-5.5 | "— done by Claude Sonnet 5.5 (jev-everyday)" | 21 s |
| 3 | Rails monolith to Kubernetes plan | large p=0.79 | yes | jev-large / claude-opus-5.5 | "— done by Claude Opus 5.5 (jev-large)" | 101 s |
| 4 | B2C to B2B pivot strategy | hardest p=0.86 | yes | jev-hardest / claude-opus-5.5 | "— done by Claude Opus 5.5 (jev-hardest)" | 67 s |

Main model was `gpt-6.1-sol` in every session; each session shows `subagent.started` / `subagent.completed` for the named
helper and the main reply repeats the helper's output and footer verbatim. No `self_error`; the env key was set. No CLI
warnings about the agent files (`model-policy`, `include-custom-instructions`, `user-invocable`, `reasoningEffort`).
Jev cost for 7 calls: 3414 input tokens, about $0.00014.

## Findings

1. **The hook also fires for the helper's own prompt** (second `userPromptTransformed` per session, stdin then carries
   `agentId`, `agentType`, `parentAgentId`; the event carries `parentToolCallId`). Runs 2 and 4 injected a second note
   into the helper's prompt; the helpers did not recurse, but it is a loop risk and it doubled Jev calls (7 for 4
   prompts). **Fixed**: the adapter now returns early when any of those keys is present; unit test added (18 tests pass);
   installed copy synced.
2. **`reasoningEffort: high` is ignored.** `subagent.configured` reports `reasoningEffort: medium` for jev-hardest. The key
   is not in the custom-agents reference, the CLI agents how-to, or `copilot help config`; the CLI accepts the file
   silently. So `large` and `hardest` are currently the same model at the same effort. Options: collapse to three helpers,
   or keep four and wait for Fable entitlement (the note and stats still distinguish them).
3. Run 3 also auto-loaded an unrelated personal skill (`nova-authoring-plan`) inside the session; not caused by the router.
4. Copilot's own `/usage` is the place to measure premium-request cost of helper calls (Phase 4).
