"""Engine and session management. SQLite is supported for tests/offline dev by dropping the `auth` schema."""
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import SCHEMA


class Database:
    def __init__(self, url: str):
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        engine = create_engine(url, pool_pre_ping=True)
        if self.is_sqlite:
            event.listen(engine, "connect", self._enable_sqlite_fks)
            engine = engine.execution_options(schema_translate_map={SCHEMA: None})
        self.engine: Engine = engine
        self._factory = sessionmaker(bind=engine, expire_on_commit=False)

    @staticmethod
    def _enable_sqlite_fks(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    def session(self) -> Session:
        return self._factory()


@lru_cache(maxsize=1)
def get_database() -> Database:
    return Database(settings.database_url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_database().session() as session:
        yield session
