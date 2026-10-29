from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "auth"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """All identity tables live in the dedicated Postgres schema `auth`."""

    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
