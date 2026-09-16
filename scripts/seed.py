"""Seed a deterministic test dataset.

Run inside the stack:

    docker compose exec api python scripts/seed.py
    docker compose exec api python scripts/seed.py --reset   # wipe first

Deterministic by design: the RNG is seeded, so every run produces byte-identical
data. That is what makes the backup/restore drill verifiable — you can compare
row counts and checksums before and after a restore and expect an exact match.

Idempotent: re-running without --reset is a no-op rather than a duplicate load.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text

# Make `app` importable when run as `python scripts/seed.py`.
sys.path.insert(0, "/home/app")

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralEvent,
    ReferralPriority,
    ReferralStatus,
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
    "Avery", "Jordan", "Riley", "Quinn", "Morgan", "Casey", "Rowan", "Skyler",
    "Emerson", "Finley", "Hayden", "Kendall", "Logan", "Parker", "Reese",
]
LAST_NAMES = [
    "Alvarez", "Boyd", "Chen", "Duarte", "Ellis", "Fowler", "Gagnon", "Haddad",
    "Ibrahim", "Jensen", "Kowalski", "Lindqvist", "Mbeki", "Nakamura", "Okonkwo",
]

# Terminal states never appear as a from_status in a later event.
TERMINAL = {ReferralStatus.COMPLETED, ReferralStatus.CANCELLED, ReferralStatus.REJECTED}


def _name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def reset(session) -> None:
    """Drop all seeded rows. TRUNCATE CASCADE also resets identity sequences."""
    log.info("resetting seeded tables")
    session.execute(
        text(
            "TRUNCATE referral_events, referrals, patients, providers, facilities "
            "RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


def already_seeded(session) -> bool:
    return session.scalar(select(func.count()).select_from(Facility)) > 0


def seed(session) -> dict[str, int]:
    """Insert the dataset and return per-table row counts."""
    rng = random.Random(RANDOM_SEED)
    now = datetime.now(timezone.utc)

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
            priority=rng.choices(
                list(ReferralPriority), weights=[70, 25, 5], k=1
            )[0],
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
            ReferralStatus.DRAFT, ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED
        ],
        ReferralStatus.SCHEDULED: [
            ReferralStatus.DRAFT, ReferralStatus.SUBMITTED,
            ReferralStatus.ACCEPTED, ReferralStatus.SCHEDULED,
        ],
        ReferralStatus.COMPLETED: [
            ReferralStatus.DRAFT, ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED,
            ReferralStatus.SCHEDULED, ReferralStatus.COMPLETED,
        ],
        ReferralStatus.CANCELLED: [
            ReferralStatus.DRAFT, ReferralStatus.SUBMITTED, ReferralStatus.CANCELLED
        ],
        ReferralStatus.REJECTED: [
            ReferralStatus.DRAFT, ReferralStatus.SUBMITTED, ReferralStatus.REJECTED
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
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.reset:
            reset(session)
        elif already_seeded(session):
            log.info("database already seeded; nothing to do (use --reset to reload)")
            return 0

        counts = seed(session)

    for table, n in counts.items():
        log.info("seeded %-16s %d rows", table, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
