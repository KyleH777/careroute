"""Application settings, loaded from the environment.

No connection details are hardcoded: dev gets them from Compose, and Azure
gets them from App Settings. Keeping this in one place means the same image
runs in both without a code change.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"

    # SQLAlchemy URL. Uses the psycopg (v3) driver.
    database_url: str = (
        "postgresql+psycopg://careroute:careroute@db:5432/careroute"
    )

    # Verify connections before handing them out. Azure closes idle
    # connections, and without this the first request after an idle period
    # fails with a stale-connection error.
    db_pool_pre_ping: bool = True
    db_pool_size: int = 5
    db_max_overflow: int = 5


settings = Settings()
