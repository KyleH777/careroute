# Constraints

Synthesized by gsd-doc-synthesizer on 2026-09-24, mode `new`.
No SPEC documents were in this ingest set, so there are no api-contract, schema or protocol constraints from SPECs.
The entries below are the explicit "Constraints" section of the PRD, recorded here so downstream planners have one place to look. They carry PRD precedence, not SPEC precedence.

---

## Budget ceiling
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- type: nfr
- content: Keep the demo under ~$20/month; scale-to-zero stays on.

## Region
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md (restating ADR-0007)
- type: nfr
- content: Region is centralus (ADR-0007). Terraform state storage remains in eastus (ADR-0007, /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/adr/0007-private-postgres-in-centralus.md).

## CI stays green, runbook stays accurate
- source: /Users/kyleharrington/Desktop/AI/Docker/CareRoute/docs/prd/PRD-production-readiness.md
- type: nfr
- content: Every change keeps CI green and the runbook accurate.
