from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Stores timezone-aware datetimes as UTC; always returns aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if url.startswith("sqlite") and (":memory:" in url or url == "sqlite://"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def init_db(url: str | None = None) -> sessionmaker[Session]:
    """Create the engine/tables and return the session factory (also stored globally)."""
    global _engine, _factory
    from app.models import task  # noqa: F401  (register models)

    _engine = make_engine(url)
    Base.metadata.create_all(_engine)
    _factory = sessionmaker(_engine, expire_on_commit=False)
    return _factory


def get_session_factory() -> sessionmaker[Session]:
    return _factory or init_db()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
