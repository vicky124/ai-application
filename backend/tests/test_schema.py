"""Offline checks that the Alembic migration (used on Postgres) stays in sync with the SQLAlchemy models."""
import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.db.models  # noqa: F401
from app.db.base import SCHEMA, Base

BACKEND = Path(__file__).resolve().parents[1]


def migration_sql() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND, capture_output=True, text=True, check=True,
        env={**os.environ, "DATABASE_URL": "postgresql+psycopg://x:x@localhost/x"},  # offline mode: never connects
    )
    return out.stdout


def model_sql() -> str:
    dialect = postgresql.dialect()
    parts = []
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)))
        parts.extend(str(CreateIndex(ix).compile(dialect=dialect)) for ix in table.indexes)
    return "\n".join(parts)


def names(sql: str, pattern: str) -> set[str]:
    return {n for n in re.findall(pattern, sql) if "alembic_version" not in n}


def test_migration_matches_models():
    mig, mod = migration_sql(), model_sql()
    for label, pattern in (("tables", r"CREATE TABLE (\S+)"), ("constraints", r"CONSTRAINT (\w+)"), ("indexes", r"CREATE INDEX (\w+)")):
        assert names(mig, pattern) == names(mod, pattern), label


def test_everything_lives_in_the_auth_schema():
    sql = migration_sql()
    assert "CREATE SCHEMA IF NOT EXISTS auth" in sql
    for table in re.findall(r"CREATE TABLE (\S+)", sql):
        assert table.startswith(f"{SCHEMA}."), table
