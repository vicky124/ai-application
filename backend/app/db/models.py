"""Identity schema (`auth`): roles with access levels, permissions, users, refresh tokens, audit log."""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA, Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(sa.types.TypeDecorator):
    """timestamptz that always round-trips as an aware UTC datetime (SQLite returns naive values)."""

    impl = sa.DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(sa.DateTime(timezone=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime not allowed; use timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


JsonType = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")  # None -> SQL NULL, not JSON null
BigIntPk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")  # SQLite only autoincrements INTEGER keys

role_permissions = sa.Table(
    "role_permissions",
    Base.metadata,
    sa.Column("role_id", sa.Integer, ForeignKey(f"{SCHEMA}.roles.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("permission_id", sa.Integer, ForeignKey(f"{SCHEMA}.permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    """A named access level. Higher `level` means broader access (employee 10 ... admin 100)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(32), unique=True)
    level: Mapped[int] = mapped_column(sa.Integer)
    description: Mapped[str] = mapped_column(sa.String(200), default="")

    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(64), unique=True)  # e.g. "users:manage"
    description: Mapped[str] = mapped_column(sa.String(200), default="")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint("username = lower(username)", name="username_lowercase"),
        sa.Index("ix_users_role_id", "role_id"),
        sa.Index("ix_users_manager_id", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True)
    email: Mapped[str | None] = mapped_column(sa.String(255), unique=True)
    full_name: Mapped[str] = mapped_column(sa.String(120))
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.roles.id"))
    department: Mapped[str] = mapped_column(sa.String(80), default="General")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, server_default=sa.true())
    failed_login_attempts: Mapped[int] = mapped_column(sa.Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, server_default=sa.func.now())

    role: Mapped[Role] = relationship(lazy="joined")

    @property
    def permission_codes(self) -> list[str]:
        return sorted(p.code for p in self.role.permissions)


class RefreshToken(Base):
    """Opaque refresh tokens, stored only as SHA-256 hashes. `family_id` links a rotation chain."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (sa.Index("ix_refresh_tokens_user_id", "user_id"), sa.Index("ix_refresh_tokens_family_id", "family_id"))

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    user_agent: Mapped[str | None] = mapped_column(sa.String(255))

    user: Mapped[User] = relationship()


class AuditLog(Base):
    """Append-only record of authentication and administration events."""

    __tablename__ = "audit_log"
    __table_args__ = (sa.Index("ix_audit_log_created_at", "created_at"), sa.Index("ix_audit_log_user_id", "user_id"))

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"))
    username: Mapped[str | None] = mapped_column(sa.String(64))  # attempted username, kept even if no such user
    action: Mapped[str] = mapped_column(sa.String(64))
    success: Mapped[bool] = mapped_column(sa.Boolean)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    detail: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, server_default=sa.func.now())
