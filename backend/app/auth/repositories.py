"""Persistence for identity data. Small, single-purpose repositories over one SQLAlchemy session.
They never commit; the services own the transaction boundary."""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import AuditLog, RefreshToken, Role, User


class RoleRepository:
    def __init__(self, session: Session):
        self._s = session

    def by_name(self, name: str) -> Role | None:
        return self._s.scalar(sa.select(Role).where(Role.name == name))

    def all(self) -> list[Role]:
        return list(self._s.scalars(sa.select(Role).order_by(Role.level, Role.name)))


class UserRepository:
    def __init__(self, session: Session):
        self._s = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._s.get(User, user_id)

    def by_username(self, username: str) -> User | None:
        return self._s.scalar(sa.select(User).where(User.username == username))

    def by_email(self, email: str) -> User | None:
        return self._s.scalar(sa.select(User).where(sa.func.lower(User.email) == email.lower()))

    def add(self, user: User) -> User:
        self._s.add(user)
        self._s.flush()
        return user

    def search(self, query: str | None, role: str | None, active: bool | None, offset: int, limit: int) -> tuple[list[User], int]:
        stmt = sa.select(User)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(
                sa.or_(User.username.like(like), sa.func.lower(User.full_name).like(like), sa.func.lower(User.email).like(like))
            )
        if role:
            stmt = stmt.join(Role, User.role_id == Role.id).where(Role.name == role)
        if active is not None:
            stmt = stmt.where(User.is_active == active)
        total = self._s.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0
        rows = self._s.scalars(stmt.order_by(User.username).offset(offset).limit(limit)).unique().all()
        return list(rows), total


class RefreshTokenRepository:
    def __init__(self, session: Session):
        self._s = session

    def add(self, token: RefreshToken) -> None:
        self._s.add(token)
        self._s.flush()

    def by_hash(self, token_hash: str) -> RefreshToken | None:
        return self._s.scalar(sa.select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        self._s.execute(
            sa.update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        self._s.execute(
            sa.update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )


class AuditRepository:
    def __init__(self, session: Session):
        self._s = session

    def add(self, action: str, success: bool, user_id: uuid.UUID | None = None, username: str | None = None,
            ip: str | None = None, detail: dict | None = None) -> None:
        self._s.add(AuditLog(action=action, success=success, user_id=user_id, username=username, ip_address=ip, detail=detail))

    def search(self, action: str | None, username: str | None, offset: int, limit: int) -> tuple[list[AuditLog], int]:
        stmt = sa.select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if username:
            stmt = stmt.where(AuditLog.username == username.lower())
        total = self._s.scalar(sa.select(sa.func.count()).select_from(stmt.subquery())) or 0
        rows = self._s.scalars(stmt.order_by(AuditLog.id.desc()).offset(offset).limit(limit)).all()
        return list(rows), total
