# Database scripts (PostgreSQL)

Standalone SQL for the identity database: the `auth` schema (roles, permissions, users, refresh tokens, audit log).
The application can create all of this itself through its Alembic migration; these scripts are for setting up or
resetting a database by hand, or for DBAs who prefer plain SQL.

| Script | What it does |
|---|---|
| [schema.sql](schema.sql) | Creates the `auth` schema, tables, constraints and indexes, and stamps Alembic at revision `0001` |
| [sample_data.sql](sample_data.sql) | Loads roles (access levels), permissions, the role-permission mapping and 9 sample users |
| [drop_schema.sql](drop_schema.sql) | `DROP SCHEMA auth CASCADE`: deletes everything, for starting over (**destructive**) |

The files are **generated** from the application code (the migration and `auth/constants.py`). Edit the source, then run
`python -m app.db.manage export-sql` from `backend/`. A test fails if the files in this folder are out of date.

## 1. Create the database and role (once, as a superuser)

```sql
CREATE ROLE policy LOGIN PASSWORD 'policy';
CREATE DATABASE policy_copilot OWNER policy;
```

(Or `docker compose up -d postgres` from the repository root, which does this for you.)

## 2. Run the scripts

With `psql`:

```bash
psql -U policy -d policy_copilot -f db/schema.sql
psql -U policy -d policy_copilot -f db/sample_data.sql
```

Without `psql`, use the project's runner (it reads `DATABASE_URL`, default
`postgresql+psycopg://policy:policy@localhost:5432/policy_copilot`):

```bash
cd backend
.venv/Scripts/python -m app.db.manage run-sql ../db/schema.sql
.venv/Scripts/python -m app.db.manage run-sql ../db/sample_data.sql
```

To start over: run `drop_schema.sql`, then `schema.sql`, then `sample_data.sql`.

## 3. How this fits with the application

- `schema.sql` stamps the migration version, so the API's startup migration (`AUTO_MIGRATE=true`) finds nothing to do.
  Running the scripts first and the app second, or the other way around, both work.
- `sample_data.sql` can be loaded before or after the app starts. If the users table already has rows, the app skips
  its own demo seeding. Loading the sample file into a database the app has already seeded is harmless: every insert uses
  `ON CONFLICT DO NOTHING`, so it only adds the extra sample users.
- Roles and permissions are upserted by name on every app start, so editing them in SQL is overwritten by the
  definitions in `backend/app/auth/constants.py`. Change them there.

## Sample accounts

Passwords are for **local development only**. They are weak on purpose and published here; never load this file into
a shared or production database.

| Username | Password | Role (level) | Manager | Status |
|---|---|---|---|---|
| `mark` | `mark123` | manager (20) | | active |
| `priya` | `priya123` | manager (20) | | active |
| `alice` | `alice123` | employee (10) | mark | active |
| `bob` | `bob123` | employee (10) | mark | active |
| `sam` | `sam123` | employee (10) | priya | active |
| `dave` | `dave123` | employee (10) | mark | **inactive** (cannot log in) |
| `hannah` | `hannah123` | hr (30) | | active |
| `carl` | `carl123` | compliance (30) | | active |
| `root` | `root123` | admin (100) | | active |

Password hashes are Argon2id with a fixed salt per user, so regenerating the file produces identical output. Audit-log
rows and refresh tokens are not included: the application creates them as people sign in.

## Roles and permissions

| Role | Level | Permissions |
|---|---|---|
| employee | 10 | `chat:use` |
| manager | 20 | `chat:use` |
| hr | 30 | `chat:use`, `documents:manage`, `users:read` |
| compliance | 30 | `chat:use`, `documents:manage`, `users:read`, `audit:read` |
| admin | 100 | all, including `users:manage` |

## Useful queries

```sql
-- Who can do what
SELECT r.name AS role, r.level, string_agg(p.code, ', ' ORDER BY p.code) AS permissions
FROM auth.roles r
LEFT JOIN auth.role_permissions rp ON rp.role_id = r.id
LEFT JOIN auth.permissions p ON p.id = rp.permission_id
GROUP BY r.id ORDER BY r.level, r.name;

-- Users with their role and manager
SELECT u.username, r.name AS role, m.username AS manager, u.is_active
FROM auth.users u
JOIN auth.roles r ON r.id = u.role_id
LEFT JOIN auth.users m ON m.id = u.manager_id
ORDER BY r.level DESC, u.username;

-- Recent security events
SELECT created_at, username, action, success, ip_address
FROM auth.audit_log ORDER BY id DESC LIMIT 20;
```

## Local cluster without Docker or admin rights

How the development database on this project's machine was created (PostgreSQL 16 binaries installed, own data folder,
port 5433). No Windows service and no superuser login are needed for the setup:

```powershell
# 1. new cluster (you type the superuser password at the prompt)
& 'C:\Program Files\PostgreSQL\16\bin\initdb.exe' -D C:\PostgreSQL16-data -U postgres -W -A scram-sha-256 -E UTF8
# 2. choose the port
Add-Content C:\PostgreSQL16-data\postgresql.conf "port = 5433"
# 3. create the app role and databases offline, in single-user mode (statements end at newline)
#    CREATE ROLE policy LOGIN PASSWORD 'policy'
#    CREATE DATABASE policy_copilot OWNER policy
#    CREATE DATABASE policy_test OWNER policy
#    fed to:  postgres.exe --single -D C:/PostgreSQL16-data postgres
# 4. start it
& 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe' start -D C:\PostgreSQL16-data -l C:\PostgreSQL16-data\server.log
```

Then point the app at it in `backend/.env`:
`DATABASE_URL=postgresql+psycopg://policy:policy@localhost:5433/policy_copilot`. A cluster started this way stops when the
machine restarts; start it again with the last command, or register it as a service (needs admin).

## Verification status

Verified on **PostgreSQL 16.15** (Windows):
- `schema.sql` and `sample_data.sql` run cleanly; re-running `sample_data.sql` changes nothing (5 roles, 5 permissions,
  14 role-permission rows, 9 users).
- The Alembic migration builds an empty database from scratch, and `pg_dump --schema-only` of that database is identical to
  the one built by `schema.sql`.
- The full test suite (59 tests) passes against Postgres (`TEST_DATABASE_URL`), and the API logs in and serves
  `/api/me` and `/api/users` from it.

The sample data is also tested on SQLite (portable SQL) so the suite stays runnable without a server.
