"""Admin CLI.

    python -m app.db.manage migrate        apply schema migrations
    python -m app.db.manage seed           upsert roles and permissions
    python -m app.db.manage create-admin   create an administrator (prompts for the password)
    python -m app.db.manage export-sql     regenerate the standalone scripts in /db
    python -m app.db.manage run-sql FILE   run a script from /db against DATABASE_URL (like psql -f)
"""
import argparse
import getpass
import sys
from pathlib import Path

from app.auth.deps import get_hasher
from app.auth.passwords import password_problems
from app.config import settings
from app.db.bootstrap import migrate, seed_reference_data
from app.db.models import Role, User
from app.db.session import get_database


def create_admin(username: str, email: str | None, full_name: str) -> int:
    import sqlalchemy as sa

    db, hasher = get_database(), get_hasher()
    username = username.strip().lower()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return 1
    problems = password_problems(password, username, settings.password_min_length)
    if problems:
        print("Password " + "; ".join(problems), file=sys.stderr)
        return 1
    with db.session() as session:
        seed_reference_data(session)
        if session.scalar(sa.select(User).where(User.username == username)):
            print(f"User '{username}' already exists", file=sys.stderr)
            return 1
        role = session.scalar(sa.select(Role).where(Role.name == "admin"))
        session.add(User(username=username, email=email, full_name=full_name, password_hash=hasher.hash(password), role_id=role.id, department="IT"))
        session.commit()
    print(f"Created admin '{username}'")
    return 0


def run_sql_file(db, path: str) -> int:
    """Runs a script (possibly many statements, including BEGIN/COMMIT) through psycopg, like `psql -f`."""
    if db.is_sqlite:
        print("run-sql targets PostgreSQL; set DATABASE_URL to a postgresql+psycopg:// URL", file=sys.stderr)
        return 1
    sql = Path(path).read_text(encoding="utf-8")
    conn = db.engine.raw_connection()
    try:
        conn.driver_connection.autocommit = True  # the scripts manage their own transactions
        conn.driver_connection.execute(sql)
    finally:
        conn.close()
    print(f"Executed {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("export-sql", help="regenerate db/schema.sql, db/sample_data.sql, db/drop_schema.sql")
    run_sql = sub.add_parser("run-sql", help="execute a .sql script against DATABASE_URL (Postgres)")
    run_sql.add_argument("file")
    admin = sub.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email")
    admin.add_argument("--full-name", default="Administrator")
    args = parser.parse_args()

    if args.cmd == "export-sql":
        from app.db.sqlgen import export_all

        for path in export_all():
            print(f"Wrote {path}")
        return 0

    db = get_database()
    if args.cmd == "run-sql":
        return run_sql_file(db, args.file)
    if args.cmd == "migrate":
        migrate(db)
        print("Schema is up to date")
    elif args.cmd == "seed":
        with db.session() as session:
            seed_reference_data(session)
        print("Roles and permissions seeded")
    elif args.cmd == "create-admin":
        return create_admin(args.username, args.email, args.full_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
