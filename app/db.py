"""Database engine, session factory, and the declarative base."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def make_engine(url: str) -> Engine:
    """The app's engine settings, for any URL (the tests reuse this)."""
    return create_engine(
        url,
        pool_pre_ping=settings.db_pool_pre_ping,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": settings.db_connect_timeout},
        future=True,
    )


engine = make_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base that Alembic autogenerate reads metadata from."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that always closes."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
