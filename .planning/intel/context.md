# Context (from DOCs)

Synthesized by gsd-doc-synthesizer on 2026-09-24, mode `new`.
No DOC-type documents were in this ingest set.

Per /Users/kyleharrington/Desktop/AI/Docker/CareRoute/.planning/ingest-manifest.yaml, these were deliberately excluded:
- docs/AZURE.md, docs/BACKUP-RESTORE.md, docs/RUNBOOK.md, docs/INCIDENT-RESPONSE.md (ops docs; mutual "see also" links form cross-ref cycles; stale Azure content is tracked as PRD requirement R8 / REQ-ops-docs-match-deployment)
- docs/adr/README.md (ADR index)
- the shipped superpowers plan/spec

Cross-refs from ingested docs that point at these excluded docs (ADR-0004 -> INCIDENT-RESPONSE.md; PRD -> adr/README.md, RUNBOOK.md, INCIDENT-RESPONSE.md, AZURE.md) are references to out-of-scope docs, not missing inputs. Their content was not read or synthesized, so any facts they contain are not reflected in this intel.
