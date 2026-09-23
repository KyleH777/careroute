# syntax=docker/dockerfile:1

# Base images are Docker Hardened Images (https://dhi.io): minimal Debian 13
# builds with no known HIGH/CRITICAL CVEs at release, rebuilt as fixes land.
#
#   *-dev   has a shell and package tooling — used only to build the venv
#   runtime has no shell, no package manager, and runs as uid 65532
#
# Both share the same interpreter at /usr/bin/python3.12, which is what lets
# a venv built in one run unchanged in the other (a venv's python is a
# symlink to the interpreter that created it).
ARG PYTHON_IMAGE=dhi.io/python:3.12-debian13

# ============================================================
# Stage 1: builder — installs dependencies into a virtualenv.
# Every dependency ships a prebuilt manylinux wheel, so no
# compilers are needed.
# ============================================================
FROM ${PYTHON_IMAGE}-dev AS builder

# Isolated venv so the runtime stage can copy one clean directory
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build

# Copy ONLY the dependency manifest first — this layer is cached
# until requirements.txt changes, so code edits don't re-install deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && pip uninstall -y pip

# ============================================================
# Stage 2: runtime — hardened, shell-less, non-root.
# There is no shell here, so this stage can have no RUN steps:
# everything it needs is copied in.
# ============================================================
FROM ${PYTHON_IMAGE} AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime artifacts only: the installed deps, app code, and the migration
# scripts. Migrations ship in the image so the exact code being deployed
# carries the exact schema it expects.
#
# Files stay owned by root and the process runs as uid 65532, so the running
# app cannot modify its own code or dependencies.
COPY --from=builder /opt/venv /opt/venv
WORKDIR /home/app
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY alembic.ini ./alembic.ini

# The base image's non-root user; restated so the intent is visible here.
USER 65532

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================
# Stage 3: test-deps — builder's venv plus dev/test-only
# dependencies (pytest, httpx, ruff, mypy). Never published.
# ============================================================
FROM builder AS test-deps

# builder uninstalled pip from its venv (see Stage 1); bring it back just
# long enough to install the dev dependencies. `python -m pip` guarantees
# the venv's pip rather than whichever `pip` PATH finds first.
RUN python -m ensurepip --upgrade

COPY requirements-dev.txt .
RUN python -m pip install --no-cache-dir -r requirements-dev.txt

# ============================================================
# Stage 4: test — the runtime image plus test-deps' venv and
# the tests/ directory. Used only by docker-compose.test.yml.
# ============================================================
FROM runtime AS test

COPY --from=test-deps /opt/venv /opt/venv
COPY tests/ ./tests/

# The code is root-owned and read-only to uid 65532 (as in runtime), so
# pytest and coverage write their scratch files to /tmp instead.
ENV COVERAGE_FILE=/tmp/.coverage

CMD ["pytest", "-v", "-p", "no:cacheprovider"]
