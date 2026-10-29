"""Builds the standalone SQL scripts in /db from the single source of truth:

* schema.sql       the Alembic migration rendered as plain SQL (offline mode), stamped with the Alembic revision
* sample_data.sql  roles, permissions, users (Argon2 hashes with fixed salts so output is reproducible)
* drop_schema.sql  removes the auth schema

Regenerate with `python -m app.db.manage export-sql`; a test fails if the files on disk are stale.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

from argon2 import PasswordHasher

from app.auth.constants import DEMO_USERS, PERMISSION_DEFS, ROLE_DEFS, ROLE_PERMISSIONS

BACKEND_DIR = Path(__file__).resolve().parents[2]
SQL_DIR = BACKEND_DIR.parent / "db"

# Extra sample accounts beyond the demo users the app seeds:
# (username, password, full name, role, department, manager username, active, has email)
EXTRA_USERS = [
    ("priya", "priya123", "Priya Patel", "manager", "Sales", None, True, True),
    ("bob", "bob123", "Bob Builder", "employee", "Engineering", "mark", True, True),
    ("sam", "sam123", "Sam Seller", "employee", "Sales", "priya", True, True),
    ("dave", "dave123", "Dave Departed", "employee", "Engineering", "mark", False, False),
]

HEADER = "-- {title}\n-- GENERATED FILE: edit the generator (backend/app/db/sqlgen.py), then run\n--   python -m app.db.manage export-sql\n"


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _user_id(username: str) -> str:
    """Stable UUID per username so sample rows (and manager links) are identical on every load."""
    h = hashlib.sha256(f"policy-copilot-sample-user:{username}".encode()).hexdigest()
    return f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-a{h[17:20]}-{h[20:32]}"


def _hash(username: str, password: str) -> str:
    salt = hashlib.sha256(f"sample-salt:{username}".encode()).digest()[:16]
    return PasswordHasher().hash(password, salt=salt)


def sample_users() -> list[tuple]:
    """(username, password, full_name, role, department, manager, active, has_email), managers before reports."""
    rows = [(u, p, n, r, d, m, True, True) for u, p, n, r, d, m in DEMO_USERS] + EXTRA_USERS
    return sorted(rows, key=lambda r: r[5] is not None)


def build_schema_sql() -> str:
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://x:x@localhost/x"}  # offline mode never connects
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR, capture_output=True, text=True, check=True, env=env,
    ).stdout
    out = re.sub(r"\s+RETURNING\s+[\w.]+;", ";", out)  # no need to echo the stamped version
    out = out.replace("-- Running upgrade  -> 0001", "-- Migration 0001: auth schema")
    note = (
        "-- Creates the `auth` schema (roles, permissions, users, refresh tokens, audit log) and stamps Alembic at\n"
        "-- revision 0001, so the application's startup migration is then a no-op.\n"
        "-- Fails if the tables already exist: run drop_schema.sql first to start over.\n"
        "-- Usage: psql -U policy -d policy_copilot -f db/schema.sql\n\n"
    )
    return HEADER.format(title="Identity schema for the Policy & HR Copilot (PostgreSQL 14+)") + note + out.strip() + "\n"


def build_sample_data_sql() -> str:
    lines = [
        HEADER.format(title="Sample data: roles, permissions and users"),
        "-- Safe to run more than once (ON CONFLICT DO NOTHING). Requires schema.sql (or the app's migration) first.",
        "-- Sample passwords are for local development ONLY. Never load this file into a shared or production database.",
        "--",
        "--   username  password    role        manager   status",
    ]
    for u, p, _, role, _, mgr, active, _ in sample_users():
        lines.append(f"--   {u:<9} {p:<11} {role:<11} {mgr or '-':<9} {'active' if active else 'inactive'}")
    lines += ["", "BEGIN;", "", "-- Roles (access levels)"]
    roles = ",\n".join(f"  ({_q(n)}, {lvl}, {_q(desc)})" for n, (lvl, desc) in ROLE_DEFS.items())
    lines.append(f"INSERT INTO auth.roles (name, level, description) VALUES\n{roles}\nON CONFLICT (name) DO NOTHING;")
    lines += ["", "-- Permissions"]
    perms = ",\n".join(f"  ({_q(c)}, {_q(d)})" for c, d in PERMISSION_DEFS.items())
    lines.append(f"INSERT INTO auth.permissions (code, description) VALUES\n{perms}\nON CONFLICT (code) DO NOTHING;")
    lines += ["", "-- Role to permission mapping"]
    pairs = ",\n".join(f"    ({_q(r)}, {_q(c)})" for r, codes in ROLE_PERMISSIONS.items() for c in codes)
    lines.append(
        "INSERT INTO auth.role_permissions (role_id, permission_id)\n"
        "SELECT r.id, p.id\nFROM auth.roles r\nJOIN auth.permissions p ON (r.name, p.code) IN (VALUES\n"
        f"{pairs}\n)\nWHERE true\nON CONFLICT DO NOTHING;"
    )
    lines += ["", "-- Users (managers first so manager_id references exist)"]
    for u, p, full_name, role, dept, mgr, active, has_email in sample_users():
        email = _q(f"{u}@example.com") if has_email else "NULL"
        manager = _q(_user_id(mgr)) if mgr else "NULL"
        lines.append(
            "INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)\n"
            f"VALUES ({_q(_user_id(u))}, {_q(u)}, {email}, {_q(full_name)}, {_q(_hash(u, p))},\n"
            f"        (SELECT id FROM auth.roles WHERE name = {_q(role)}), {_q(dept)}, {manager}, {'true' if active else 'false'})\n"
            "ON CONFLICT (username) DO NOTHING;"
        )
    lines += ["", "COMMIT;", ""]
    return "\n".join(lines)


def build_drop_sql() -> str:
    return (
        HEADER.format(title="Removes the auth schema and everything in it")
        + "-- DESTRUCTIVE: deletes all users, sessions and audit history. Local development only.\n"
        + "-- Usage: psql -U policy -d policy_copilot -f db/drop_schema.sql\n\n"
        + "DROP SCHEMA IF EXISTS auth CASCADE;\n"
    )


def export_all(directory: Path = SQL_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    files = {"schema.sql": build_schema_sql(), "sample_data.sql": build_sample_data_sql(), "drop_schema.sql": build_drop_sql()}
    paths = []
    for name, content in files.items():
        path = directory / name
        path.write_text(content, encoding="utf-8", newline="\n")
        paths.append(path)
    return paths
