# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: builder — installs dependencies into a virtualenv.
# Build tools (compilers, headers) live ONLY here and never
# reach the final image.
# ============================================================
FROM python:3.12-slim AS builder

# Build tools for any deps that compile C extensions (numpy, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv so the runtime stage can copy one clean directory
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build

# Copy ONLY the dependency manifest first — this layer is cached
# until requirements.txt changes, so code edits don't re-install deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pip

# ============================================================
# Stage 2: runtime — minimal image, only runtime artifacts.
# No pip cache, no compilers, no source-control files.
# ============================================================
FROM python:3.12-slim AS runtime

# Patch OS packages: the python:3.12-slim base image lags Debian's own repos,
# which already carry fixes for critical CVEs in perl-base and libc6. This
# picks up those fixes without waiting on an upstream image rebuild.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# pip is never invoked at runtime (deps are already installed into the venv
# we copy in below) but the base image ships its own system-Python pip, and
# pip vendors old copies of msgpack/setuptools that scanners flag as
# vulnerable. Removing it drops those findings entirely.
RUN python3 -m pip uninstall -y pip 2>/dev/null; \
    rm -rf /usr/local/lib/python3.12/site-packages/pip* \
        /usr/local/bin/pip*

# Never run as root inside the container
RUN groupadd --system app && useradd --system --gid app --create-home app

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime artifacts only: the installed deps, app code, and the migration
# scripts. Migrations ship in the image so the exact code being deployed
# carries the exact schema it expects.
COPY --from=builder /opt/venv /opt/venv
WORKDIR /home/app
COPY --chown=app:app app/ ./app/
COPY --chown=app:app migrations/ ./migrations/
COPY --chown=app:app scripts/ ./scripts/
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
