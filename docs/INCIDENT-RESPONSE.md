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
| Bad deploy | Roll back to the previous `sha-` image (RUNBOOK → Bad deploy) |
| Database down | Restart it; the api reconnects automatically (RUNBOOK → Database unreachable) |
| Compromised account | Set `is_active = false`: effective on its **next request** (RUNBOOK → Lock out a user) |
| Leaked `JWT_SECRET` | Rotate it: invalidates **all** tokens at once |
| Bad data change | **Snapshot first**, then restore or point-in-time restore (RUNBOOK → Data loss) |

### 3. Preserve evidence

Before changing anything you can't undo:

```bash
./scripts/backup.sh incident-$(date -u +%Y%m%dT%H%M%SZ)     # database as it is now
docker compose logs --timestamps > backups/incident-logs-$(date -u +%Y%m%dT%H%M%SZ).txt
```

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
- **Token or signing key exposure:** rotate `JWT_SECRET`.
- **Database credentials exposed:** rotate the Postgres password, update
  `DATABASE_URL`, restart the api.
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
| Secret rotation | `JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))") docker compose up -d api`, then `docker compose up -d api` to go back | Every old token fails; new logins work |
