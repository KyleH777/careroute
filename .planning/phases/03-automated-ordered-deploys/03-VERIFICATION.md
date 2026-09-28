---
phase: 03-automated-ordered-deploys
status: passed
verified: 2026-09-28
---

# Phase 3 Verification: Automated Ordered Deploys

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | A push to main deploys its sha- tag without manual action; active revision + migrate job run it; /ready 200; serialized | PASS | Run 36373063429 (push of 6069293, no human step): smoke "/ready 200; api image …sha-6069293; migrate image …sha-6069293; active revision careroute-api--0000003". Concurrency `deploy-production` (no cancel) + state lease |
| 2 | Migrate exits 0 before any app revision with the new image; no single apply moves both | PASS | Stage 1 "1 changed" (migrate job only); `careroute-migrate-554qohl` Succeeded 01:44:47 → `careroute-api--0000002` created 01:45:56. Separate required image vars close the hazard by design |
| 3 | Failing-migration drill stops at migrate; old revision serves; no new revision | PASS | Run 36374139943: migrate `careroute-migrate-2tei68o` Failed ("drill: simulated migration failure"), stage 2/smoke skipped, active still `--0000003` (sha-6069293), no `--0000004`, /ready 200 |
| 4 | No Azure credential in GitHub; OIDC subject restricted to the production env (main only); roles scoped to careroute-rg + state container | PASS | Federated credential `repo:KyleH777@88053223/careroute@1383757448:environment:production` only; env branch policy `main`; GitHub holds IDs only. Grants: careroute-rg (Contributor, conditioned RBAC Admin, KV Secrets Officer on its vault), tfstate container, Reader on its own identity (careroute-ci-rg, read-only) |
| 5 | The secret-read risk is accepted and documented; no tfplan artifacts / secret output; runbook lists CI | PASS | ADR-0011 Consequences; RUNBOOK "Who can read production secrets"; deploy.sh keeps output on the runner, no upload-artifact / -out / show |

Deviation from the criterion 4 wording: one extra read-only grant outside careroute-rg (Reader on careroute-ci-id), needed for the main config's lookup; it can't modify federated credentials.
