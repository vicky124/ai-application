-- Sample data: roles, permissions and users
-- GENERATED FILE: edit the generator (backend/app/db/sqlgen.py), then run
--   python -m app.db.manage export-sql

-- Safe to run more than once (ON CONFLICT DO NOTHING). Requires schema.sql (or the app's migration) first.
-- Sample passwords are for local development ONLY. Never load this file into a shared or production database.
--
--   username  password    role        manager   status
--   mark      mark123     manager     -         active
--   hannah    hannah123   hr          -         active
--   carl      carl123     compliance  -         active
--   root      root123     admin       -         active
--   priya     priya123    manager     -         active
--   alice     alice123    employee    mark      active
--   bob       bob123      employee    mark      active
--   sam       sam123      employee    priya     active
--   dave      dave123     employee    mark      inactive

BEGIN;

-- Roles (access levels)
INSERT INTO auth.roles (name, level, description) VALUES
  ('employee', 10, 'Standard employee: policy Q&A'),
  ('manager', 20, 'People manager: employee access plus team approvals'),
  ('hr', 30, 'HR operations: manages documents, views users'),
  ('compliance', 30, 'Compliance: manages documents, views users and audit log'),
  ('admin', 100, 'Administrator: full access including user management')
ON CONFLICT (name) DO NOTHING;

-- Permissions
INSERT INTO auth.permissions (code, description) VALUES
  ('chat:use', 'Ask questions in the policy assistant'),
  ('documents:manage', 'Upload, replace and delete policy documents'),
  ('users:read', 'View users and roles'),
  ('users:manage', 'Create, update, deactivate users and reset passwords'),
  ('audit:read', 'View the authentication and administration audit log')
ON CONFLICT (code) DO NOTHING;

-- Role to permission mapping
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r
JOIN auth.permissions p ON (r.name, p.code) IN (VALUES
    ('employee', 'chat:use'),
    ('manager', 'chat:use'),
    ('hr', 'chat:use'),
    ('hr', 'documents:manage'),
    ('hr', 'users:read'),
    ('compliance', 'chat:use'),
    ('compliance', 'documents:manage'),
    ('compliance', 'users:read'),
    ('compliance', 'audit:read'),
    ('admin', 'chat:use'),
    ('admin', 'documents:manage'),
    ('admin', 'users:read'),
    ('admin', 'users:manage'),
    ('admin', 'audit:read')
)
WHERE true
ON CONFLICT DO NOTHING;

-- Users (managers first so manager_id references exist)
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('5fa47e89-8675-4a63-a67f-b30b4524338e', 'mark', 'mark@example.com', 'Mark Manager', '$argon2id$v=19$m=65536,t=3,p=4$3OoX8O5uDYOM7Ep57VO2Cw$PKH7e99ZQYcGilgsGW4w3bJ4HHif0nRacSjxPd5i3XI',
        (SELECT id FROM auth.roles WHERE name = 'manager'), 'Engineering', NULL, true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('b9b76ebb-acb5-4061-a546-87d224d6f6bc', 'hannah', 'hannah@example.com', 'Hannah HR', '$argon2id$v=19$m=65536,t=3,p=4$sV2hE8pSaVtsxQqS1KwXeA$PHiPV7wUqi4GLve8el8rnRLBdVew4hdrM2RNe5c9qWM',
        (SELECT id FROM auth.roles WHERE name = 'hr'), 'HR', NULL, true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('ca0a923e-18dc-48c2-a919-f467ca0b9222', 'carl', 'carl@example.com', 'Carl Compliance', '$argon2id$v=19$m=65536,t=3,p=4$QH94W8Nl99GKY1IUMjs9jQ$ngcAE5TxqMn7eyqjDxX6dmwC1j566e95vSDuIoZSIuk',
        (SELECT id FROM auth.roles WHERE name = 'compliance'), 'Legal', NULL, true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('f57d16ff-7c49-4c5e-a1fc-4d0682e5b986', 'root', 'root@example.com', 'Admin', '$argon2id$v=19$m=65536,t=3,p=4$ggMi75phoVYXU/uls/JNdA$44a/uTjtSjLbV2enqramZqdqQuyXeRqhlptdzwj6hfs',
        (SELECT id FROM auth.roles WHERE name = 'admin'), 'IT', NULL, true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('19f0584a-3040-42d0-a6e9-bff1d4c97e42', 'priya', 'priya@example.com', 'Priya Patel', '$argon2id$v=19$m=65536,t=3,p=4$89H7lfMC5HnZaQVMCs1RNw$wlU3JTYxSp/ZWlKoVgO1eNGzYe4putQ5K8IVE76aeZw',
        (SELECT id FROM auth.roles WHERE name = 'manager'), 'Sales', NULL, true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('dbb57434-5186-4003-a0c6-27585291f024', 'alice', 'alice@example.com', 'Alice Employee', '$argon2id$v=19$m=65536,t=3,p=4$QEt2k6tLX615PC9fOa8OdA$MHKPVu7v0/MYTWTRAV2rFmURBVlhZ/gSvATQvPLg8cg',
        (SELECT id FROM auth.roles WHERE name = 'employee'), 'Engineering', '5fa47e89-8675-4a63-a67f-b30b4524338e', true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('1349292a-3b6c-4fd9-ae01-df8fc46fc40e', 'bob', 'bob@example.com', 'Bob Builder', '$argon2id$v=19$m=65536,t=3,p=4$5wbpC9dpUgIJPBikTaOgOw$2E/t6YmYOzsuvFlV7iEjQU3lZYyyZb59k5wc8K2DKq0',
        (SELECT id FROM auth.roles WHERE name = 'employee'), 'Engineering', '5fa47e89-8675-4a63-a67f-b30b4524338e', true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('9c223269-7996-4435-a96c-f8338866ec74', 'sam', 'sam@example.com', 'Sam Seller', '$argon2id$v=19$m=65536,t=3,p=4$/C/udUjKeLeic2T6uk60Zg$4Pc2jiUL51dn3Tlwl4THYs1B+rcW4gQlZ5DPhkyg1+w',
        (SELECT id FROM auth.roles WHERE name = 'employee'), 'Sales', '19f0584a-3040-42d0-a6e9-bff1d4c97e42', true)
ON CONFLICT (username) DO NOTHING;
INSERT INTO auth.users (id, username, email, full_name, password_hash, role_id, department, manager_id, is_active)
VALUES ('f69fa372-1a77-4e34-aebb-b3e43ae9338b', 'dave', NULL, 'Dave Departed', '$argon2id$v=19$m=65536,t=3,p=4$7/xChk1rH0oVpHcEMOpcmA$abj+ojlOqBIF2fWzM7RAtCQ3deqhx6zJiC7a14UDxSE',
        (SELECT id FROM auth.roles WHERE name = 'employee'), 'Engineering', '5fa47e89-8675-4a63-a67f-b30b4524338e', false)
ON CONFLICT (username) DO NOTHING;

COMMIT;
