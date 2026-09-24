## Conflict Detection Report

Ingest set: 10 docs (9 ADR, 1 PRD) per /Users/kyleharrington/Desktop/AI/Docker/CareRoute/.planning/ingest-manifest.yaml. Mode: new. Precedence: ADR > SPEC > PRD > DOC, no per-doc overrides.

### BLOCKERS (0)

None. All 9 ADRs are locked and Accepted; no two locked ADRs make contradicting decisions on the same scope. No UNKNOWN or low-confidence classifications. No cross-ref cycles among in-scope docs.

### WARNINGS (0)

None. Only one PRD was ingested, so there are no competing acceptance variants.

### INFO (5)

[INFO] Cross-ref graph is acyclic; out-of-scope refs ignored
  Found: In-scope edges are ADR-0008 -> ADR-0006 and PRD -> ADR-0001, ADR-0006, ADR-0007, ADR-0008, ADR-0009 (source: docs/adr/0008-secrets-generated-into-key-vault.md, docs/prd/PRD-production-readiness.md). Refs to docs/INCIDENT-RESPONSE.md (from docs/adr/0004-audit-actor-from-token.md), docs/RUNBOOK.md, docs/AZURE.md and docs/adr/README.md (from the PRD) point at docs excluded by the manifest.
  Note: The three-color DFS found no cycles, and max depth is 2. The excluded ops docs were not read, so nothing they say is reflected in the intel. Their staleness is tracked as PRD R8.

[INFO] PRD is consistent with every locked ADR; it closes ADR open work instead of contradicting it
  Found: PRD R2 implements the CI-enforced deploy order from ADR-0001. R4 covers the rate limiting and login logging that ADR-0003 and ADR-0009 list as not done. R5 closes the read and provider-assignment logging gaps from ADR-0004. R6 closes the least-privilege role gap from ADR-0007. The PRD's out-of-scope list (refresh tokens, RS256) matches ADR-0003. Region centralus matches ADR-0007 (source: docs/prd/PRD-production-readiness.md; docs/adr/0001, 0003, 0004, 0007, 0009).
  Note: Nothing needed auto-resolution. Planners must keep ADR-0003's identical 401 and dummy-hash timing behavior when adding R4.1's 429 responses and R4.2's per-attempt logging. R6's new role passwords should follow ADR-0008 (Terraform random_password into Key Vault, read via managed identity).

[INFO] Planning hazard: PRD R2.1 "terraform apply with new sha- tag" could roll the app before the migrate job
  Found: docs/prd/PRD-production-readiness.md R2.1 orders the steps as terraform plan/apply with the new sha- tag, then the migrate job, then rolling the Container App. docs/adr/0001-one-shot-migration-before-api.md (locked) requires the migration to exit 0 before the API serves the new code.
  Note: The documents agree on the intent, so this is not a contradiction. But if one terraform apply updates both the migrate job image and the Container App image, the app revision rolls during apply, before the migration runs. That would violate ADR-0001 and R2.3. The roadmapper or planner should design the pipeline so ADR-0001's order holds. Options: a two-phase apply, keeping the app image out of the first apply, or setting the app image after the migration succeeds.

[INFO] Planning hazard: CI OIDC identity (R2.2) will be able to read every secret through Terraform state
  Found: docs/prd/PRD-production-readiness.md R2.2 scopes CI to "the CareRoute resource groups" so it can run terraform plan/apply. docs/adr/0006-terraform-state-backend.md says anyone with Storage Blob Data Reader on the state blob can read every secret. docs/adr/0008-secrets-generated-into-key-vault.md says secrets are also in state and that plan files embed secrets.
  Note: This does not contradict either ADR. It does mean the CI federated identity joins the small group that can read secrets, and CI-produced tfplan artifacts must not be uploaded or logged. Scope the OIDC subject (branch/environment) narrowly when planning R2.

[INFO] PRD status is Draft; R1 already done
  Found: docs/prd/PRD-production-readiness.md is "Status: Draft, input to the next GSD milestone"; R1 (verified live deployment) is marked done 2026-09-24, and R2 through R8 are open.
  Note: REQ-verified-live-deployment is recorded as completed in intel/requirements.md, so the roadmapper should not schedule it again.
