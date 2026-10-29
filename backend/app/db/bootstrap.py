"""Database initialization: schema (migrations or create_all), reference data, optional demo users."""
import logging
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.auth.constants import DEMO_USERS, PERMISSION_DEFS, ROLE_DEFS, ROLE_PERMISSIONS
from app.auth.passwords import PasswordHasher
from app.config import settings
from app.db.base import SCHEMA, Base
from app.db.models import Permission, Role, User
from app.db.session import Database

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def migrate(db: Database) -> None:
    """Postgres: run Alembic to head. SQLite (tests/offline): create tables directly."""
    if db.is_sqlite:
        Base.metadata.create_all(db.engine)
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = db.url
    command.upgrade(cfg, "head")


def seed_reference_data(session: Session) -> None:
    """Idempotently upsert roles, permissions and their mapping from app.auth.constants."""
    perms = {p.code: p for p in session.scalars(sa.select(Permission))}
    for code, desc in PERMISSION_DEFS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            session.add(perms[code])
        else:
            perms[code].description = desc
    roles = {r.name: r for r in session.scalars(sa.select(Role))}
    for name, (level, desc) in ROLE_DEFS.items():
        role = roles.get(name) or Role(name=name)
        role.level, role.description = level, desc
        session.add(role)
        roles[name] = role
    session.flush()
    for name, codes in ROLE_PERMISSIONS.items():
        roles[name].permissions = [perms[c] for c in codes]
    session.commit()


def seed_demo_users(session: Session, hasher: PasswordHasher) -> int:
    """Creates the demo accounts if the users table is empty. Local development only."""
    if session.scalar(sa.select(sa.func.count()).select_from(User)):
        return 0
    roles = {r.name: r for r in session.scalars(sa.select(Role))}
    created: dict[str, User] = {}
    for username, password, full_name, role, department, manager in DEMO_USERS:
        user = User(
            username=username, email=f"{username}@example.com", full_name=full_name,
            password_hash=hasher.hash(password), role_id=roles[role].id, department=department,
            manager_id=created[manager].id if manager else None,
        )
        session.add(user)
        session.flush()
        created[username] = user
    session.commit()
    return len(created)


def init_database(db: Database, hasher: PasswordHasher) -> None:
    if settings.auto_migrate:
        migrate(db)
    with db.session() as session:
        seed_reference_data(session)
        if settings.seed_demo_users:
            n = seed_demo_users(session, hasher)
            if n:
                log.warning("Seeded %d demo users (SEED_DEMO_USERS=true). Disable this outside local development.", n)
    if settings.jwt_secret == "dev-only-change-me":
        log.warning("JWT_SECRET is the development default. Set a long random value before deploying.")
