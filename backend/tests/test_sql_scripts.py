"""The standalone scripts in /db must stay in sync with the code and load correctly.

schema.sql is Postgres DDL, so it is checked structurally (it comes straight from the Alembic migration, which
test_schema.py compares with the models). sample_data.sql uses portable SQL, so it is executed for real against
SQLite with an attached `auth` database and then inspected.
"""
import re
import uuid

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.auth.constants import PERMISSION_DEFS, ROLE_DEFS, ROLE_PERMISSIONS
from app.db import sqlgen
from app.db.base import Base

SCHEMA_SQL = sqlgen.SQL_DIR / "schema.sql"
SAMPLE_SQL = sqlgen.SQL_DIR / "sample_data.sql"
DROP_SQL = sqlgen.SQL_DIR / "drop_schema.sql"


def read(path):
    return path.read_text(encoding="utf-8")


def test_scripts_are_up_to_date():
    expected = {
        SCHEMA_SQL: sqlgen.build_schema_sql(),
        SAMPLE_SQL: sqlgen.build_sample_data_sql(),
        DROP_SQL: sqlgen.build_drop_sql(),
    }
    for path, content in expected.items():
        assert read(path).replace("\r\n", "\n") == content, f"{path.name} is stale: run `python -m app.db.manage export-sql`"


def test_schema_script_creates_every_table_and_stamps_alembic():
    sql = read(SCHEMA_SQL)
    for table in Base.metadata.sorted_tables:
        assert f"CREATE TABLE auth.{table.name} (" in sql, table.name
    assert "INSERT INTO auth.alembic_version (version_num) VALUES ('0001');" in sql
    assert sql.count("BEGIN;") == 1 and sql.rstrip().endswith("COMMIT;")
    assert "RETURNING" not in sql


def test_drop_script_only_touches_auth_schema():
    statements = [l for l in read(DROP_SQL).splitlines() if l and not l.startswith("--")]
    assert statements == ["DROP SCHEMA IF EXISTS auth CASCADE;"]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("ATTACH DATABASE ':memory:' AS auth"))
    Base.metadata.create_all(engine)  # creates auth.* tables inside the attached database
    yield engine
    engine.dispose()


def load_sample(engine):
    raw = engine.raw_connection()
    raw.driver_connection.executescript(read(SAMPLE_SQL))
    raw.close()


def scalar(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def test_sample_data_loads_and_is_consistent(db):
    load_sample(db)
    assert scalar(db, "SELECT count(*) FROM auth.roles") == len(ROLE_DEFS)
    assert scalar(db, "SELECT count(*) FROM auth.permissions") == len(PERMISSION_DEFS)
    assert scalar(db, "SELECT count(*) FROM auth.role_permissions") == sum(len(v) for v in ROLE_PERMISSIONS.values())
    assert scalar(db, "SELECT count(*) FROM auth.users") == len(sqlgen.sample_users())
    with db.connect() as c:
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        levels = dict(c.execute(text("SELECT name, level FROM auth.roles")).fetchall())
        assert levels == {name: lvl for name, (lvl, _) in ROLE_DEFS.items()}
        admin_perms = {r[0] for r in c.execute(text(
            "SELECT p.code FROM auth.role_permissions rp JOIN auth.roles r ON r.id = rp.role_id "
            "JOIN auth.permissions p ON p.id = rp.permission_id WHERE r.name = 'admin'"))}
        assert admin_perms == set(PERMISSION_DEFS)


def test_sample_users_have_valid_passwords_roles_and_managers(db):
    load_sample(db)
    hasher = PasswordHasher()
    with db.connect() as c:
        rows = {
            r.username: r
            for r in c.execute(text(
                "SELECT u.id, u.username, u.email, u.password_hash, u.department, u.manager_id, u.is_active, r.name AS role "
                "FROM auth.users u JOIN auth.roles r ON r.id = u.role_id"))
        }
    for username, password, full_name, role, dept, manager, active, has_email in sqlgen.sample_users():
        row = rows[username]
        assert hasher.verify(row.password_hash, password), username
        assert row.role == role and row.department == dept and bool(row.is_active) == active
        assert (row.email is not None) == has_email
        assert row.manager_id == (rows[manager].id if manager else None), username
        assert uuid.UUID(row.id).version == 4
    assert rows["alice"].manager_id == rows["mark"].id and rows["sam"].manager_id == rows["priya"].id
    assert not rows["dave"].is_active  # sample of a deactivated account


def test_sample_data_is_idempotent(db):
    load_sample(db)
    load_sample(db)
    for table, expected in (("roles", 5), ("permissions", 5), ("role_permissions", 14), ("users", len(sqlgen.sample_users()))):
        assert scalar(db, f"SELECT count(*) FROM auth.{table}") == expected, table


def test_sample_data_output_is_reproducible():
    assert sqlgen.build_sample_data_sql() == sqlgen.build_sample_data_sql()  # fixed salts: identical hashes every run


def test_no_real_secrets_in_scripts():
    sample = read(SAMPLE_SQL)
    assert "local development ONLY" in sample
    assert not re.search(r"jwt|secret", sample, re.I)
