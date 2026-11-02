# Spike S4 result: Copilot CLI hook failure modes (2026-10-29)

Environment: Copilot CLI 1.0.105, `--model claude-haiku-5.5`, one `userPromptSubmitted` command hook at a time in
`~/.copilot/hooks/zz-s4-spike.json` (removed afterwards). Prompt: "What is 2+2? Answer in one short sentence."
Raw scripts, CLI output and log excerpts in `s4-raw/`.

## Verdict: all three failure modes are fail-open and silent to the user.

| Scenario | Exit | Wall s | Marker reached model | Answered | User-visible warning | Log |
|---|---|---|---|---|---|---|
| A: `sleep 20`, `timeoutSec: 3` | 0 | 17 | no | "4." | none | `[WARNING] [rust:hooks] Hook ... timed out; allowing processing to proceed: HookTimeoutError: Hook command timed out after 3 seconds` |
| B: stdout JSON + `exit 1` | 0 | 10 | no | "4" | none | `[ERROR] [rust:hooks] Hook ... execution failed: Error: Hook command failed with code 1` / `Stderr: fail.sh: deliberate failure` |
| C: `this is not json {`, exit 0 | 0 | 11 | no | "2+2 is 4." | none | `[DEBUG] [rust:hooks] [hook stdout] this is not json {` only; no parse warning |

Details:
- Timeout kills the hook: `slow.log` has the start line only, no `sleep`/`slow.sh` process survived (checked right after and
  25 s later). The CLI also logged `killpg(12000) failed: Operation not permitted (os error 1)`, so the process-group
  signal failed and the kill arrived by another route. A hook that spawns detached children might leak; unverified.
- Non-zero exit discards stdout even when it is valid JSON. Stderr is logged at ERROR.
- Invalid JSON on exit 0 is ignored at DEBUG level. No warning anywhere.
- Scenario A's extra wall time (17 s vs 10-11 s) is mostly model latency (14 s model turn); the CLI did not wait 20 s.

## Consequences for the plan

1. The adapter's fail-open contract matches Claude Code's: on Jev timeout/error, print nothing and exit 0. Keep
   `timeoutSec: 3` in the hook file as a hard ceiling over router.py's internal 1.5 s Jev timeout.
2. Because the CLI never surfaces hook problems to the user, `jev router status` must report its own last error (from
   `decisions.log` / `state.json`), and the installer's self-test should run a dry `transform` and check the JSON.
3. Non-zero exit = silent drop. The adapter must never use exit codes to signal anything; always exit 0.
4. The `killpg` EPERM suggests the hook runs in a different process group than the CLI expects. Do not rely on the CLI to
   reap grandchildren; the adapter must not fork.
