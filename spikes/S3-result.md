# Spike S3 result: Copilot CLI model IDs (2026-10-29)

Environment: GitHub Copilot CLI 1.0.105 (`copilot update`: "No update needed"). The CLI had moved from 1.0.88 to
1.0.105 on its own between S1 and S3, so pin and re-check versions in every spike. Raw outputs in `s3-raw/`.

## Verdict

| Size | Claude Code alias | Copilot CLI ID | `--model` test | Note |
|---|---|---|---|---|
| tiny | haiku (5.5) | `claude-haiku-5.5` | accepted, used (0.42 credits) | |
| everyday | sonnet (5.5) | `claude-sonnet-5.5` | accepted, used (8.38 credits) | |
| large | opus (5.5) | `claude-opus-5.5` | accepted, used (16.57 credits) | |
| hardest | fable (5.1) | `claude-fable-5.1` | **rejected**: `Error: Model "claude-fable-5.1" from --model flag is not available.` | ID is valid in the CLI schema (`copilot help config` lists `claude-fable-5.1` and `claude-fable-5`) but **absent from this account's model catalog**. Entitlement gap, not a naming gap. |

Also accepted: `claude-haiku-4.5` (provider reports `claude-haiku-4-5-20251001`). Also in catalog, untested: `claude-sonnet-5`.

Catalog fetched from CAPI (41 models, from `~/.copilot/logs/process-1793264210015-97681.log`):
claude-haiku-4.5, claude-haiku-5.5, claude-opus-5.5, claude-sonnet-5.5, claude-sonnet-5, gemini-3.8-flash,
gemini-4-argon, gpt-3.5-turbo(-0613), gpt-4(-0613), gpt-4-o-preview, gpt-4.1(-2025-04-14), gpt-41-copilot,
gpt-4o(-2024-05-13|08-06|11-20), gpt-4o-mini(-2024-07-18), gpt-5.3-codex, gpt-5.4-nano, gpt-5.6-luna(-utility),
gpt-5.6-sol(-fast), gpt-5.6-terra, gpt-6-astra, gpt-6-luna, gpt-6-sol, gpt-6.1-sol, gpt-6.1-terra, grok-4.6, grok-4.7,
mai-code-1.1-flash, mai-code-2-flash, microsoft-decision-1, text-embedding-3-small(-inference), text-embedding-ada-002.

Other findings:
- `--model` overrides the default. Default model is `gpt-6.1-sol` ("Using default model" in log). The managed-settings
  log shows a server policy with keys `[model, permissions]` and `permissions.model has an unsupported or malformed
  value and was ignored`, so no admin model lock is in effect now. The S1 banner "administrator-managed setting" did not
  reappear; unverified what the server `model` key holds.
- 1.0.105 no longer prints "Using model ..." on stdout; the model used is only visible in the log (`selected_model`).
- Neither `copilot --help` nor an invalid `--model` prints the valid list. The catalog line in the log is the source.
- Each test run spends real AI credits (about 28 total here, Opus most).
- Unverified: hyphenated forms like `claude-haiku-5-5`; the `/model` interactive list.

## Consequences for the plan

1. **Pin `hardest` to `claude-opus-5.5`** on this account. Keep `claude-fable-5.1` as the preferred entry only where a
   preference list is supported (VS Code `model:` array). In the CLI, `model-policy: required` plus an unavailable model
   would make `jev-hardest` fail, so the installer should probe the catalog (or run `copilot -p` with `--model`) and
   write the first available ID into the agent file.
2. With Fable absent, `large` and `hardest` both land on Opus 5.5. Either collapse them (three helpers) or give
   `hardest` `reasoningEffort: high` on Opus to keep a real difference. Decide in Phase 1.
3. Update the "done by" footers to the model actually pinned.
