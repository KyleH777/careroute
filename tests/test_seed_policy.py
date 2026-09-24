"""The demo-credential policy in scripts/seed.py: a password that can change
data is never the published one outside development."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "seed", Path(__file__).resolve().parents[1] / "scripts" / "seed.py"
)
assert _spec and _spec.loader
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)

VIEWER = "viewer@careroute.demo"
CLINICIAN = "clinician@careroute.demo"
COORDINATOR = "coordinator@careroute.demo"
PRIVATE = {
    "DEMO_CLINICIAN_PASSWORD": "c" * 24,
    "DEMO_COORDINATOR_PASSWORD": "k" * 24,
}


@pytest.mark.parametrize("env", ["local", "dev", "test"])
def test_dev_envs_use_published_password_for_everyone(env):
    passwords = seed.demo_passwords(env, demo_deployment=False, environ={})
    assert set(passwords.values()) == {seed.DEMO_PASSWORD}
    assert set(passwords) == {VIEWER, CLINICIAN, COORDINATOR}


def test_production_without_flag_is_refused():
    with pytest.raises(seed.SeedRefused, match="--demo-deployment"):
        seed.demo_passwords("production", demo_deployment=False, environ=PRIVATE)


def test_demo_deployment_publishes_only_the_viewer_password():
    passwords = seed.demo_passwords("production", demo_deployment=True, environ=PRIVATE)
    assert passwords[VIEWER] == seed.DEMO_PASSWORD
    assert passwords[CLINICIAN] == "c" * 24
    assert passwords[COORDINATOR] == "k" * 24


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"DEMO_CLINICIAN_PASSWORD": "c" * 24},
        {**PRIVATE, "DEMO_COORDINATOR_PASSWORD": "too-short"},
    ],
    ids=["none-set", "coordinator-missing", "coordinator-too-short"],
)
def test_demo_deployment_requires_strong_private_passwords(environ):
    with pytest.raises(seed.SeedRefused, match="at least 16 characters"):
        seed.demo_passwords("production", demo_deployment=True, environ=environ)


def test_demo_deployment_rejects_published_password_for_writers():
    environ = {**PRIVATE, "DEMO_CLINICIAN_PASSWORD": seed.DEMO_PASSWORD + "-padding"}
    assert seed.demo_passwords("production", True, environ)  # merely similar: fine

    environ = {**PRIVATE, "DEMO_CLINICIAN_PASSWORD": seed.DEMO_PASSWORD}
    with pytest.raises(seed.SeedRefused):
        seed.demo_passwords("production", True, environ)
