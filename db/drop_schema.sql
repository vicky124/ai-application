-- Removes the auth schema and everything in it
-- GENERATED FILE: edit the generator (backend/app/db/sqlgen.py), then run
--   python -m app.db.manage export-sql
-- DESTRUCTIVE: deletes all users, sessions and audit history. Local development only.
-- Usage: psql -U policy -d policy_copilot -f db/drop_schema.sql

DROP SCHEMA IF EXISTS auth CASCADE;
