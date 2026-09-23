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
_DEV_ENVS = {"local", "test"}


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
    db_max_overflow: int = 5

    # HS256 signing key for access tokens. Generate a real one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = 60

    @model_validator(mode="after")
    def _require_real_secret(self) -> "Settings":
        """Fail fast rather than sign production tokens with a public key."""
        if self.app_env not in _DEV_ENVS and self.jwt_secret == DEV_JWT_SECRET:
            raise ValueError(
                f"JWT_SECRET must be set when APP_ENV={self.app_env!r}; "
                "the built-in default is for local development only"
            )
        return self


settings = Settings()
