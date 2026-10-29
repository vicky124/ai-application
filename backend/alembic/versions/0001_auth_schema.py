"""Create the auth schema: roles, permissions, users, refresh tokens, audit log.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

S = "auth"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {S}")

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
        schema=S,
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
        schema=S,
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer, nullable=False),
        sa.Column("permission_id", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(["role_id"], [f"{S}.roles.id"], name="fk_role_permissions_role_id_roles", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["permission_id"], [f"{S}.permissions.id"], name="fk_role_permissions_permission_id_permissions", ondelete="CASCADE"
        ),
        schema=S,
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role_id", sa.Integer, nullable=False),
        sa.Column("department", sa.String(80), nullable=False, server_default="General"),
        sa.Column("manager_id", sa.Uuid, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_login_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("username = lower(username)", name="username_lowercase"),  # naming convention yields ck_users_username_lowercase
        sa.ForeignKeyConstraint(["role_id"], [f"{S}.roles.id"], name="fk_users_role_id_roles"),
        sa.ForeignKeyConstraint(["manager_id"], [f"{S}.users.id"], name="fk_users_manager_id_users", ondelete="SET NULL"),
        schema=S,
    )
    op.create_index("ix_users_role_id", "users", ["role_id"], schema=S)
    op.create_index("ix_users_manager_id", "users", ["manager_id"], schema=S)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.Uuid, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        sa.ForeignKeyConstraint(["user_id"], [f"{S}.users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"),
        schema=S,
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema=S)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], schema=S)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid, nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(["user_id"], [f"{S}.users.id"], name="fk_audit_log_user_id_users", ondelete="SET NULL"),
        schema=S,
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], schema=S)
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"], schema=S)


def downgrade() -> None:
    for table in ("audit_log", "refresh_tokens", "users", "role_permissions", "permissions", "roles"):
        op.drop_table(table, schema=S)
