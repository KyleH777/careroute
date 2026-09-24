# ADR-0005: Docker Hardened Images as the base image

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

The `python:3.12-slim` runtime carried unfixable HIGH CVEs (perl, zlib) plus a shell and package manager an attacker could use.

## Decision

Build on `dhi.io/python:3.12-debian13-dev` and run on `dhi.io/python:3.12-debian13`: no shell, no package manager, non-root uid 65532, app files root-owned and read-only to the process. Both share `/usr/bin/python3.12`, so the build-stage virtualenv runs unchanged. Images are multi-arch (amd64 + arm64).

## Consequences

- 325 MB to 234 MB. CI's Trivy gate fails on any fixable HIGH/CRITICAL.
- A plain Scout scan still lists six base-image HIGHs; Docker's VEX marks all six `not_affected`. With `--vex-location` it's 0/0. Attaching the VEX to our image was tested and Scout did **not** apply it, so docs state the accurate status instead of claiming a clean scan.
- Builds and CI need a Docker account to pull from dhi.io (`DOCKERHUB_*` secrets).
- No shell for debugging; use `docker debug`.
