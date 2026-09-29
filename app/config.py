"""Application settings, loaded from the environment.

No connection details are hardcoded: dev gets them from Compose, and Azure
gets them from App Settings. Keeping this in one place means the same image
runs in both without a code change.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only acceptable where APP_ENV says nothing real is at stake. Anywhere else,
# Settings refuses to start with it (see _require_real_secret).
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"
DEV_ENVS = {"local", "dev", "test"}


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"

    # SQLAlchemy URL. Uses the psycopg (v3) driver.
    database_url: str = "postgresql+psycopg://careroute:careroute@db:5432/careroute"

    # Verify connections before handing them out. Azure closes idle
    # connections, and without this the first request after an idle period
    # fails with a stale-connection error.
    db_pool_pre_ping: bool = True
    db_pool_size: int = 5
    # Give up on a new connection after this many seconds. Without it, a
    # stopped or unreachable server makes every request (and /ready) hang on
    # the TCP connect: during the 2026-09-28 drill /ready took a median of
    # 130 s to return 503. Fail fast instead.
    db_connect_timeout: int = 5
    db_max_overflow: int = 5

    # HS256 signing key for access tokens. Generate a real one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = 60

    # Login rate limiting (ADR-0013): failures in a sliding window, counted in
    # Postgres so every replica agrees and restarts don't reset it.
    login_window_seconds: int = 900
    login_max_failures_per_email: int = 5
    login_max_failures_per_ip: int = 20
    # How many reverse proxies append to X-Forwarded-For in front of the app.
    # 0 (local): use the socket peer. 1 (Azure Container Apps): the rightmost
    # entry, which ingress appends; anything a client forges sits left of it.
    trusted_proxy_hops: int = 0

    @model_validator(mode="after")
    def _require_real_secret(self) -> "Settings":
        """Fail fast rather than sign production tokens with a public key."""
        if self.app_env not in DEV_ENVS and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError(
                f"JWT_SECRET must be set when APP_ENV={self.app_env!r}; "
                "the built-in default is for local development only"
            )
        return self


settings = Settings()
