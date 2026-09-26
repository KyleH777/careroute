# Incident Response

How an incident is declared, run, communicated and closed. For the technical
fixes, what to check and what to run, see **[RUNBOOK.md](RUNBOOK.md)**.

CareRoute holds patient records (names, dates of birth, MRNs, contact details,
referral reasons). In a real deployment that is **protected health
information (PHI)**, so any incident that might have exposed data follows the
[security path](#security-incidents-and-possible-phi-exposure) below, not just
the outage path.

---

## What counts as an incident

Declare one if **any** of these is true:

- Referrals can't be created, read or routed (the core workflow is down)
- Error rate is clearly elevated (a burst of 500s, `/ready` returning 503)
- Data is wrong, missing, or was changed by someone who shouldn't have
- A credential, secret, backup file or database dump may have leaked
- An account is behaving in a way its owner doesn't recognize

**When in doubt, declare.** Downgrading a false alarm costs minutes;
under-reacting to a real breach costs far more.

---

## Severity

| Sev | Definition | Examples | Response |
|---|---|---|---|
| **SEV1** | Service down for everyone, **or** confirmed/likely PHI exposure, **or** data loss | Database down; `JWT_SECRET` leaked; a dump found in a public place; mass unauthorized changes | Immediately, all hands. Status updates every **30 min** |
| **SEV2** | Core workflow degraded for many users, no data at risk | Login failing for all users; worklist erroring; bad deploy | Within **1 hour**. Updates every **60 min** |
| **SEV3** | Partial or cosmetic impact, workaround exists | One endpoint erroring; slow responses; CI red (production unaffected) | Next business day |

Severity can change as you learn more. Re-rate out loud and note it in the
timeline. **Any suspicion of PHI exposure is SEV1 until ruled out.**

---

## Roles

For a small team, one person may hold several roles, but name them explicitly.

| Role | Does | Does **not** |
|---|---|---|
| **Incident Commander (IC)** | Owns the incident: sets severity, assigns work, decides when it's resolved | Debug. The IC coordinates |
| **Operations lead** | Diagnoses and fixes using the runbook | Communicate externally |
| **Communications lead** | Status updates to stakeholders; drafts notifications | Speculate about cause |
| **Scribe** | Keeps the timeline: every action, with a UTC timestamp | Filter. Log everything |

---

## The process

### 1. Declare

- Open an incident channel/doc named `inc-YYYYMMDD-<short-name>`.
- Post: what's broken, when it started, severity, who is IC.
- Start the timeline immediately. Times in **UTC**.

### 2. Stabilize: stop the bleeding before finding the cause

Restore service first; root cause comes later. From the runbook:

| Situation | Fastest mitigation |
|---|---|
| Bad deploy | Roll back to the previous `sha-` image (RUNBOOK → Bad deploy). Azure: set `image` in `infra/variables.tf`, then `terraform apply` |
| Database down | Restart it; the api reconnects automatically (RUNBOOK → Database unreachable). Azure: `az postgres flexible-server start` or `restart` |
| Compromised account | Set `is_active = false`: effective on its **next request** (RUNBOOK → Lock out a user) |
| Leaked `JWT_SECRET` | Rotate it: invalidates **all** tokens at once (RUNBOOK → Invalidate everyone's tokens). Azure: `terraform apply -replace=random_password.jwt_secret`, then restart the revision |
| Bad data change | **Snapshot first**, then restore or point-in-time restore (RUNBOOK → Data loss). Azure: note the UTC time, then PITR to a *new* server |

### 3. Preserve evidence

Before changing anything you can't undo:

```bash
./scripts/backup.sh incident-$(date -u +%Y%m%dT%H%M%SZ)     # database as it is now
docker compose logs --timestamps > backups/incident-logs-$(date -u +%Y%m%dT%H%M%SZ).txt
```

**Azure:** there is no `backup.sh`. Instead:

- **Write down the UTC time.** Point-in-time restore to a new server can
  recover the database as it was at any moment in the last 7 days, so the
  timestamp *is* the snapshot. Don't restore yet unless you need to
  ([AZURE.md → Backups and restore](AZURE.md#backups-and-restore)).
- **Export the logs now.** Log Analytics keeps 30 days, and ingestion stops for
  the day past the 0.5 GB cap. Query `ContainerAppConsoleLogs_CL` for the
  incident window and save the results into `backups/`
  ([AZURE.md → Logs](AZURE.md#logs)).

Treat these as sensitive: they may contain PHI. Store them with restricted
access, **never** in git, chat, or a ticket attachment. Both commands write
into `backups/`, which is git-ignored for exactly this reason.

### 4. Communicate

Post updates on the severity's cadence, even if the update is "no change."
Template:

> **[SEV#] <title>, update #N, HH:MM UTC**
> **Impact:** who can't do what.
> **Status:** investigating / identified / mitigated / resolved.
> **What we've done:** …
> **Next update:** HH:MM UTC.

Say what you **know**, not what you suspect. Never guess at scope of data
exposure in a broad update; that goes through the security path.

### 5. Resolve

Resolved means: the service works (RUNBOOK verification steps pass), the
cause is contained, and nothing is still getting worse. Post a final update.
Downgrading from mitigated to resolved is the IC's call.

### 6. Post-incident review

Within **5 business days** for SEV1/SEV2. Blameless: the question is "what
let this happen?", not "who did it?". Use the template below.

---

## Security incidents and possible PHI exposure

Run this **in addition to** the process above whenever data may have been
accessed, changed or leaked by someone unauthorized.

### Contain

- **Specific accounts:** deactivate them (`is_active = false`).
- **Token or signing key exposure:** rotate `JWT_SECRET`. Azure:
  `terraform apply -replace=random_password.jwt_secret`, which writes a new
  version of Key Vault secret `jwt-secret`. Then
  `az containerapp revision restart` on the active `careroute-api` revision so
  it takes effect now rather than within 30 minutes. Expect every session to
  get 401.
- **Database credentials exposed:** Azure: `terraform apply -replace=random_password.postgres_admin`.
  That single apply changes the server's admin password **and** the
  `database-url` Key Vault secret. Nobody edits `DATABASE_URL` by hand. Then
  restart the active `careroute-api` revision. Between the apply and the
  restart, `/ready` returns 503. Jobs pick up the new value on their next run.
  Compose (dev): change the password and `DATABASE_URL` together, then
  `docker compose up -d api`.
- **Terraform state or a `*.tfplan` file exposed:** both contain **every**
  secret. Rotate all four `random_password` resources, and review who holds
  Storage Blob Data Reader on the state account
  ([ADR-0006](adr/0006-terraform-state-backend.md)). Steps for each:
  [AZURE.md → Secrets and rotation](AZURE.md#secrets-and-rotation).
- **Leaked dump or backup file:** get it taken down; identify which backup it
  was (timestamp in the filename) to know what data it held.

### Scope: what can we actually prove?

What the system records:

```sql
-- every status change, attributed to the authenticated account
select occurred_at, actor, referral_id, from_status, to_status, note
from referral_events
where occurred_at between '<start>' and '<end>'
order by occurred_at;

-- which accounts exist, their roles, and whether they're active
select email, role, is_active, created_at from users order by created_at;
```

`actor` is trustworthy: it comes from the verified token and **cannot** be set
by the client (enforced and tested).

**Be explicit about what the system does *not* record.** It shapes what you
can tell regulators and patients:

- **Reads are not logged.** If an account was compromised, you **cannot**
  prove which patient records it viewed. Scope has to assume everything that
  account's role could read.
- **Provider assignments are not logged.**
- **There is no access log of login attempts,** so brute-forcing isn't
  visible, and there is **no login rate limiting**.
- Log retention is whatever the container runtime keeps. There is no
  central log store yet.

### Notify

This is a **legal/compliance decision, not an engineering one.** Engineering's
job is to hand them accurate facts: what data, how many patients, what time
window, how we know.

For HIPAA-covered data, the Breach Notification Rule requires notifying
affected individuals **without unreasonable delay and no later than 60 days
after discovery**. Breaches affecting **500 or more** people also require
notifying HHS (and, for 500+ in one state, the media) within the same window.
Smaller breaches are reported to HHS annually. **Confirm current obligations
with your compliance officer or counsel.** The clock starts at *discovery*,
which is why suspected exposure is SEV1 from the first minute.

---

## Known limitations (fix before real PHI)

These gaps directly limit incident response. They are the priority list:

| Gap | Why it matters in an incident |
|---|---|
| No read/access logging | Can't scope what a compromised account viewed |
| No login rate limiting or failed-login log | Password guessing is invisible |
| No monitoring or alerting | Incidents are found by users, not by us. `/ready` returns 503 correctly, but nothing watches it yet |
| No central log retention | Evidence disappears with the container |
| Assignment not in the audit log | Can't reconstruct who routed a patient where |
| Single-region, single database | No failover; a database outage is a full outage |

---

## Post-incident review template

```markdown
# PIR: <title> (inc-YYYYMMDD-<name>)

**Severity:** SEV#   **Duration:** start → resolved (UTC)   **IC:** <name>

## Summary
Two or three sentences a non-engineer can follow.

## Impact
Who was affected, what they couldn't do, for how long. Any data involved.

## Timeline (UTC)
- HH:MM  first symptom
- HH:MM  detected (how?)
- HH:MM  declared, SEV#
- HH:MM  mitigated
- HH:MM  resolved

## Root cause
What actually happened, technically. Keep asking "why?" past the first answer.

## What went well / what didn't
Including detection: how long between start and detection, and why?

## Action items
| Action | Owner | Due | Ticket |
|---|---|---|---|
| Prevent recurrence | | | |
| Detect it faster | | | |
| Recover faster | | | |
```

---

## Practice

An untested plan is a guess. Drills worth running, all safe on the dev stack:

| Drill | How | Proves |
|---|---|---|
| Database outage | `docker compose stop db`, work the runbook, `docker compose start db` | `/ready` goes 503; api recovers on its own |
| Restore | The full drill in BACKUP-RESTORE.md | Backups actually restore, verified by fingerprint |
| Compromised account | Deactivate a demo user mid-session | Their existing token is rejected on the next request |
| Secret rotation (dev stack) | `JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))") docker compose up -d api`, then `docker compose up -d api` to go back | Every old token fails; new logins work |

An Azure rotation drill (RUNBOOK → Invalidate everyone's tokens) logs out
the live demo and restarts the API. Run it only with the owner's go-ahead.
