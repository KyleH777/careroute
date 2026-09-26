"""Seed a deterministic test dataset.

Run inside the stack:

    docker compose exec api python scripts/seed.py
    docker compose run --rm migrate python scripts/seed.py --reset   # wipe first

--reset truncates, which only the schema owner (careroute_migrate) may do, so
it runs through the migrate service rather than the DML-only api (ADR-0010).

Deterministic by design: the RNG is seeded, so every run produces byte-identical
data. That is what makes the backup/restore drill verifiable — you can compare
row counts and checksums before and after a restore and expect an exact match.

Idempotent: re-running without --reset is a no-op rather than a duplicate load.

Also creates one demo login per role (see DEMO_USERS). Password policy lives
in demo_passwords():

- local/dev/test: every demo user gets the published DEMO_PASSWORD.
- anywhere else: refused, unless run with --demo-deployment. Then only the
  read-only viewer gets the published password; clinician and coordinator
  (who can write) take private passwords from DEMO_CLINICIAN_PASSWORD and
  DEMO_COORDINATOR_PASSWORD, and --reset is refused outright.

So a password that can change data is never published outside development.

    python scripts/seed.py --demo-deployment      # e.g. the Azure seed job
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text

# Make `app` importable when run as `python scripts/seed.py`.
sys.path.insert(0, "/home/app")

from app.auth import hash_password
from app.config import DEV_ENVS, settings
from app.db import SessionLocal
from app.models import (
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralEvent,
    ReferralPriority,
    ReferralStatus,
    User,
    UserRole,
)

RANDOM_SEED = 42

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed")

CITIES = [
    ("Boston", "MA", "America/New_York"),
    ("Cambridge", "MA", "America/New_York"),
    ("Providence", "RI", "America/New_York"),
    ("Hartford", "CT", "America/New_York"),
    ("Portland", "ME", "America/New_York"),
]

SPECIALTIES = [
    "Cardiology",
    "Endocrinology",
    "Orthopedics",
    "Neurology",
    "Dermatology",
    "Pulmonology",
]

FIRST_NAMES = [
    "Avery",
    "Jordan",
    "Riley",
    "Quinn",
    "Morgan",
    "Casey",
    "Rowan",
    "Skyler",
    "Emerson",
    "Finley",
    "Hayden",
    "Kendall",
    "Logan",
    "Parker",
    "Reese",
]
LAST_NAMES = [
    "Alvarez",
    "Boyd",
    "Chen",
    "Duarte",
    "Ellis",
    "Fowler",
    "Gagnon",
    "Haddad",
    "Ibrahim",
    "Jensen",
    "Kowalski",
    "Lindqvist",
    "Mbeki",
    "Nakamura",
    "Okonkwo",
]

# Terminal states never appear as a from_status in a later event.
TERMINAL = {ReferralStatus.COMPLETED, ReferralStatus.CANCELLED, ReferralStatus.REJECTED}


# Demo logins, one per role. Documented in the README; dev/test only.
DEMO_PASSWORD = "careroute-demo"
DEMO_USERS = [
    ("viewer@careroute.demo", "Vera Viewer", UserRole.VIEWER),
    ("clinician@careroute.demo", "Cal Clinician", UserRole.CLINICIAN),
    ("coordinator@careroute.demo", "Cora Coordinator", UserRole.COORDINATOR),
]


# Minimum length for the private (write-capable) demo passwords.
MIN_PRIVATE_PASSWORD_LENGTH = 16
_PRIVATE_PASSWORD_ENV = {
    UserRole.CLINICIAN: "DEMO_CLINICIAN_PASSWORD",
    UserRole.COORDINATOR: "DEMO_COORDINATOR_PASSWORD",
}


class SeedRefused(Exception):
    """The seed would violate the demo-credential policy; nothing was written."""


def demo_passwords(
    app_env: str, demo_deployment: bool, environ: dict[str, str]
) -> dict[str, str]:
    """Return {email: password} for DEMO_USERS, or raise SeedRefused.

    Pure: no database, no global state. See the module docstring for the
    policy this enforces.
    """
    if app_env in DEV_ENVS:
        return {email: DEMO_PASSWORD for email, _, _ in DEMO_USERS}

    if not demo_deployment:
        raise SeedRefused(
            f"refusing to seed APP_ENV={app_env!r}: pass --demo-deployment to "
            "seed a public demo (viewer gets the published password; "
            "write-capable roles need private passwords)"
        )

    passwords: dict[str, str] = {}
    for email, _, role in DEMO_USERS:
        if role == UserRole.VIEWER:
            passwords[email] = DEMO_PASSWORD
            continue
        var = _PRIVATE_PASSWORD_ENV[role]
        value = environ.get(var, "")
        if len(value) < MIN_PRIVATE_PASSWORD_LENGTH:
            raise SeedRefused(
                f"{var} must be set to at least {MIN_PRIVATE_PASSWORD_LENGTH} "
                f"characters for a demo deployment ({role.value} can write data, "
                "so its password is never the published one)"
            )
        if value == DEMO_PASSWORD:
            raise SeedRefused(f"{var} must not be the published demo password")
        passwords[email] = value
    return passwords


def _name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def reset(session) -> None:
    """Drop all seeded rows. TRUNCATE CASCADE also resets identity sequences."""
    log.info("resetting seeded tables")
    session.execute(
        text(
            "TRUNCATE referral_events, referrals, patients, providers, facilities, "
            "users RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def already_seeded(session) -> bool:
    return session.scalar(select(func.count()).select_from(Facility)) > 0


def ensure_demo_users(session, passwords: dict[str, str]) -> int:
    """Create any missing DEMO_USERS; return how many were added.

    Separate from seed() and run on every invocation, so a database seeded
    before the users table existed still gets its demo logins.
    """
    existing = set(session.scalars(select(User.email)))
    missing = [u for u in DEMO_USERS if u[0] not in existing]
    session.add_all(
        User(
            email=email,
            full_name=name,
            password_hash=hash_password(passwords[email]),
            role=role,
        )
        for email, name, role in missing
    )
    session.commit()
    return len(missing)


def seed(session) -> dict[str, int]:
    """Insert the dataset and return per-table row counts."""
    rng = random.Random(RANDOM_SEED)
    now = datetime.now(UTC)

    facilities = [
        Facility(name=f"{city} Community Health", city=city, state=st, timezone=tz)
        for city, st, tz in CITIES
    ]
    session.add_all(facilities)
    session.flush()

    providers = []
    for i in range(24):
        providers.append(
            Provider(
                facility_id=rng.choice(facilities).id,
                # Zero-padded to satisfy the 10-digit NPI check constraint.
                npi=f"{1000000000 + i * 7919:010d}"[:10],
                full_name=f"Dr. {_name(rng)}",
                specialty=rng.choice(SPECIALTIES),
                accepting_new_patients=rng.random() > 0.25,
            )
        )
    session.add_all(providers)
    session.flush()

    patients = []
    for i in range(120):
        birth = date(1945, 1, 1) + timedelta(days=rng.randint(0, 27000))
        patients.append(
            Patient(
                mrn=f"MRN{100000 + i}",
                full_name=_name(rng),
                date_of_birth=birth,
                phone=f"617-555-{rng.randint(1000, 9999)}",
                email=None if rng.random() < 0.2 else f"patient{i}@example.invalid",
            )
        )
    session.add_all(patients)
    session.flush()

    referrals: list[Referral] = []
    events: list[ReferralEvent] = []
    for i in range(300):
        specialty = rng.choice(SPECIALTIES)
        status = rng.choices(
            list(ReferralStatus),
            weights=[5, 20, 18, 22, 25, 5, 5],
            k=1,
        )[0]
        # Only assign a provider once the referral has left draft/submitted.
        assigned = (
            rng.choice([p for p in providers if p.specialty == specialty] or providers)
            if status not in {ReferralStatus.DRAFT, ReferralStatus.SUBMITTED}
            else None
        )
        created = now - timedelta(days=rng.randint(0, 180), hours=rng.randint(0, 23))

        ref = Referral(
            patient_id=rng.choice(patients).id,
            origin_facility_id=rng.choice(facilities).id,
            assigned_provider_id=assigned.id if assigned else None,
            status=status,
            priority=rng.choices(list(ReferralPriority), weights=[70, 25, 5], k=1)[0],
            specialty_requested=specialty,
            reason=f"Routine referral #{i} for {specialty.lower()} evaluation.",
            created_at=created,
            updated_at=created,
        )
        referrals.append(ref)
    session.add_all(referrals)
    session.flush()

    # Build a plausible transition chain ending at each referral's status.
    chain_to = {
        ReferralStatus.DRAFT: [ReferralStatus.DRAFT],
        ReferralStatus.SUBMITTED: [ReferralStatus.DRAFT, ReferralStatus.SUBMITTED],
        ReferralStatus.ACCEPTED: [
            ReferralStatus.DRAFT,
            ReferralStatus.SUBMITTED,
            ReferralStatus.ACCEPTED,
        ],
        ReferralStatus.SCHEDULED: [
            ReferralStatus.DRAFT,
            ReferralStatus.SUBMITTED,
            ReferralStatus.ACCEPTED,
            ReferralStatus.SCHEDULED,
        ],
        ReferralStatus.COMPLETED: [
            ReferralStatus.DRAFT,
            ReferralStatus.SUBMITTED,
            ReferralStatus.ACCEPTED,
            ReferralStatus.SCHEDULED,
            ReferralStatus.COMPLETED,
        ],
        ReferralStatus.CANCELLED: [
            ReferralStatus.DRAFT,
            ReferralStatus.SUBMITTED,
            ReferralStatus.CANCELLED,
        ],
        ReferralStatus.REJECTED: [
            ReferralStatus.DRAFT,
            ReferralStatus.SUBMITTED,
            ReferralStatus.REJECTED,
        ],
    }
    for ref in referrals:
        chain = chain_to[ref.status]
        prev: ReferralStatus | None = None
        stamp = ref.created_at
        for st in chain:
            events.append(
                ReferralEvent(
                    referral_id=ref.id,
                    from_status=prev,
                    to_status=st,
                    actor="seed-script",
                    note=None,
                    occurred_at=stamp,
                )
            )
            prev = st
            stamp = stamp + timedelta(hours=rng.randint(1, 72))
    session.add_all(events)
    session.commit()

    return {
        "facilities": len(facilities),
        "providers": len(providers),
        "patients": len(patients),
        "referrals": len(referrals),
        "referral_events": len(events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed CareRoute test data.")
    parser.add_argument(
        "--reset", action="store_true", help="truncate seeded tables before loading"
    )
    parser.add_argument(
        "--demo-deployment",
        action="store_true",
        help="allow seeding outside local/dev/test as a public read-only demo",
    )
    args = parser.parse_args()

    try:
        passwords = demo_passwords(
            settings.app_env, args.demo_deployment, dict(os.environ)
        )
    except SeedRefused as exc:
        log.error("%s", exc)
        return 1

    if args.reset and settings.app_env not in DEV_ENVS:
        log.error("refusing --reset outside local/dev/test: it wipes every table")
        return 1

    with SessionLocal() as session:
        if args.reset:
            reset(session)
        elif already_seeded(session):
            added = ensure_demo_users(session, passwords)
            log.info(
                "database already seeded; added %d missing demo user(s) "
                "(use --reset to reload everything)",
                added,
            )
            return 0

        counts = seed(session)
        counts["users"] = ensure_demo_users(session, passwords)

    for table, n in counts.items():
        log.info("seeded %-16s %d rows", table, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
