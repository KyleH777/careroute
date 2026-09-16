"""CareRoute API — placeholder entrypoint.

Replace this module with your real CareRoute code. The Dockerfile
expects an ASGI app at ``app.main:app``; keep that path or update
the CMD line in the Dockerfile to match.
"""

from fastapi import FastAPI

app = FastAPI(title="CareRoute")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by the container HEALTHCHECK."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    """Placeholder root route."""
    return {"service": "CareRoute", "message": "Paste your app code into app/"}

