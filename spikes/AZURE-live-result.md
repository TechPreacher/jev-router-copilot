# Live test: Microsoft Decision-1 in Azure AI Foundry as the sizing backend (2026-11-04)

## Verdict: PASS

The upstream `router.py` (the copy in `files/`), run by hand from a shell with a scratch `JEV_ROUTER_HOME`, against a
real `Microsoft-Decision-1` deployment (GlobalStandard) on a Foundry resource with local auth disabled. The endpoint and
deployment name were passed as environment variables for the test only and are not recorded here: the router treats
both as secrets.

## Procedure

1. `router.py on` with `JEV_AZURE_ENDPOINT` and `JEV_AZURE_DEPLOYMENT` set, `TYPESAFE_API_KEY` unset. It fetched an
   Entra token through the signed-in Azure CLI (scope `https://ai.azure.com/.default`) in 1.8 s and wrote
   `azure-token.json` (mode 600, 64 minutes of validity).
2. `router.py hook` with the four canned prompts from the README's testing section, one per size.

## First attempt: 401 PermissionDenied

Every call returned `{"error":{"code":"PermissionDenied","message":"Principal does not have access to API/Operation."}}`,
with tokens for both `https://ai.azure.com/.default` and `https://cognitiveservices.azure.com/.default`. The identity
was Owner on the subscription (control plane) but had no data-plane role on the resource, and `disableLocalAuth: true`
ruled out an API key. The hook failed open each time: exit 0, nothing printed, `status` showed `last error`. Assigning
`Cognitive Services User` on the resource fixed it after about five minutes of propagation.

## Result

| Prompt | Decision-1 | p | confidence | input tokens | latency | route |
|---|---|---|---|---|---|---|
| What is the HTTP status code for not found? | tiny | 0.999 | 0.999 | 104 | 503 ms | jev-tiny |
| Draft a two-sentence thank-you email to a colleague who covered my shift. | everyday | 0.561 | 0.415 | 110 | 423 ms | kept (unsure) |
| Research the main options for migrating our reporting from Postgres to ClickHouse and write a full report with a comparison table. | large | 0.997 | 0.997 | 118 | 460 ms | jev-large |
| Should we rewrite our billing system in-house or buy a vendor? Give me a strategy and the risks of each. | hardest | 0.983 | 0.977 | 117 | 487 ms | jev-hardest |

- Response shape identical to TypeSafe's (`answers.size.choice`, `probabilities`, `confidence`, `usage.input_tokens`);
  the response's `model` names the underlying model, not the deployment.
- Latency 420 to 500 ms per call, inside the 1.5 s budget.
- The everyday prompt scored 0.56 twice (0.59 on an earlier run), under `MIN_SURE` 0.60, so the main model kept it.
  Jev routes that prompt at a higher probability. A deployment-specific threshold is a possible follow-up; the four
  criteria texts were not tuned for Decision-1.
- `decisions.log` records `"backend": "azure"` on every line; `status` names the backend and never the endpoint.

## Not covered

- A Copilot CLI or VS Code session with the Azure backend (this was the core's hook from a shell).
- The background refresh against a real `az` under the 3 s hook (covered offline with a stub `az`).
- Windows with the Azure values in the Credential Manager (offline-tested in CI).
