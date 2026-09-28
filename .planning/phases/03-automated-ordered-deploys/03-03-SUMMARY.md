---
phase: 03-automated-ordered-deploys
plan: 03
status: complete
requirements: [DEPLOY-01, DEPLOY-02, DEPLOY-03]
completed: 2026-09-28
---

# 03-03 Summary: docs

- ADR-0011 (two-stage CI Terraform deploy, OIDC environment subject in immutable-ID form, bounded CI identity, declined alternative, **accepted risk**); ADR index updated.
- AZURE.md: the "Deploying a new image" section is rewritten (CI stages, rollback/drill via workflow_dispatch); new "Running Terraform by hand" (`TF_IMAGES` from outputs, TF_VAR_operator_object_id, don't apply during a deploy, commit infra changes) and "Job environments"; first-time deployment now creates infra/ci first, with required image vars and no plan files; architecture adds careroute-ci-rg/-id; rotation/teardown commands pass TF_IMAGES.
- RUNBOOK.md: rollback 2a via `image_tag`, 2b downgrade-then-redeploy (a deploy without the downgrade fails safely at migrate); "CI is red" gets 6 deploy rows (AADSTS700213 subject, AuthorizationFailed, state lock, transient secrets read, migrate, smoke); new "Who can read production secrets" list (criterion 5), incl. the CI identity and anyone who can push to main, with a one-command cut-off.
- INCIDENT-RESPONSE.md: bad-deploy mitigation via image_tag; rotation commands with TF_IMAGES; a compromised-CI containment path.
- README: the CI description includes the ordered deploy.
Checks: all new anchors resolve; no stale variables.tf-image or plan-file instructions remain.
