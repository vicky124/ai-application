from alembic import context
from sqlalchemy import create_engine, pool, text

import app.db.models  # noqa: F401  (registers tables on Base.metadata)
from app.config import settings
from app.db.base import SCHEMA, Base

config = context.config
# Programmatic runs (app startup) pass the URL via config.attributes; the CLI falls back to settings.
url = config.attributes.get("database_url") or settings.database_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` prints the DDL without connecting."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # The version table lives in the auth schema, so the schema must exist before Alembic touches it.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
