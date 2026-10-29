import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

GOOD_PW = "Sup3r-secret-pw"
NEW_PW = "An0ther-secret-pw"


def hdr(access):
    return {"Authorization": f"Bearer {access}"}


def login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def make_user(client, admin, role="employee", password=GOOD_PW, **extra):
    name = "u" + uuid.uuid4().hex[:8]
    body = {"username": name, "password": password, "full_name": f"User {name}", "role": role, **extra}
    r = client.post("/api/users", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def session_for(client, admin, role="employee"):
    user = make_user(client, admin, role)
    data = login(client, user["username"], GOOD_PW).json()
    return user, data


# ---------------- login ----------------
def test_login_returns_tokens_and_user(client):
    r = login(client, "alice", "alice123")
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer" and data["expires_in"] == settings.access_token_minutes * 60
    assert data["user"]["role"] == "employee" and data["user"]["permissions"] == ["chat:use"]
    claims = jwt.decode(data["access_token"], options={"verify_signature": False})
    assert claims["type"] == "access" and claims["role"] == "employee" and claims["level"] == 10 and claims["iss"] == settings.jwt_issuer


def test_bad_credentials_are_indistinguishable(client):
    wrong_pw = login(client, "alice", "nope-nope-nope")
    unknown = login(client, "nobody-here", "nope-nope-nope")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()
    assert wrong_pw.headers["www-authenticate"] == "Bearer"


def test_username_is_case_insensitive(client):
    assert login(client, "  ALICE ", "alice123").status_code == 200


def test_lockout_after_repeated_failures(client, admin):
    user = make_user(client, admin)
    for _ in range(settings.max_failed_logins):
        assert login(client, user["username"], "wrong-password-1").status_code == 401
    assert login(client, user["username"], GOOD_PW).status_code == 423  # correct password is refused while locked
    events = client.get("/api/audit-log", headers=admin, params={"username": user["username"]}).json()["items"]
    assert any(e["action"] == "account_locked" for e in events)


def test_successful_login_resets_failure_counter(client, admin):
    user = make_user(client, admin)
    for _ in range(settings.max_failed_logins - 1):
        login(client, user["username"], "wrong-password-1")
    assert login(client, user["username"], GOOD_PW).status_code == 200
    for _ in range(settings.max_failed_logins - 1):
        assert login(client, user["username"], "wrong-password-1").status_code == 401
    assert login(client, user["username"], GOOD_PW).status_code == 200  # counter was reset, so still not locked


# ---------------- tokens ----------------
def test_me_requires_valid_token(client, alice):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=alice).json()["username"] == "alice"


def test_bad_tokens_are_rejected(client, admin):
    user, data = session_for(client, admin)
    secret = settings.jwt_secret
    now = datetime.now(timezone.utc)
    base = {"iss": settings.jwt_issuer, "sub": user["id"], "iat": int(now.timestamp()), "type": "access"}
    cases = {
        "expired": jwt.encode({**base, "exp": now - timedelta(minutes=1)}, secret, algorithm="HS256"),
        "wrong secret": jwt.encode({**base, "exp": now + timedelta(minutes=5)}, "x" * 40, algorithm="HS256"),
        "wrong issuer": jwt.encode({**base, "iss": "evil", "exp": now + timedelta(minutes=5)}, secret, algorithm="HS256"),
        "wrong type": jwt.encode({**base, "type": "refresh", "exp": now + timedelta(minutes=5)}, secret, algorithm="HS256"),
        "unknown user": jwt.encode({**base, "sub": str(uuid.uuid4()), "exp": now + timedelta(minutes=5)}, secret, algorithm="HS256"),
        "not a uuid": jwt.encode({**base, "sub": "123", "exp": now + timedelta(minutes=5)}, secret, algorithm="HS256"),
        "alg none": jwt.encode({**base, "exp": now + timedelta(minutes=5)}, None, algorithm="none"),
        "refresh token as bearer": data["refresh_token"],
        "garbage": "not.a.jwt",
    }
    for name, tok in cases.items():
        assert client.get("/api/me", headers=hdr(tok)).status_code == 401, name
    assert client.get("/api/me", headers=hdr(data["access_token"])).status_code == 200


def test_refresh_rotates_and_detects_reuse(client, admin):
    _, data = session_for(client, admin)
    first = data["refresh_token"]
    second = client.post("/auth/refresh", json={"refresh_token": first})
    assert second.status_code == 200 and second.json()["refresh_token"] != first
    assert client.get("/api/me", headers=hdr(second.json()["access_token"])).status_code == 200

    # Replaying the already-used token is treated as theft: the whole chain is revoked.
    assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}).status_code == 401


def test_logout_revokes_refresh_token_and_is_idempotent(client, admin):
    _, data = session_for(client, admin)
    assert client.post("/auth/logout", json={"refresh_token": data["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401
    assert client.post("/auth/logout", json={"refresh_token": "x" * 40}).status_code == 204


def test_logout_all_revokes_every_session(client, admin):
    user, first = session_for(client, admin)
    second = login(client, user["username"], GOOD_PW).json()
    assert client.post("/auth/logout-all", headers=hdr(first["access_token"])).status_code == 204
    for d in (first, second):
        assert client.post("/auth/refresh", json={"refresh_token": d["refresh_token"]}).status_code == 401


# ---------------- password management ----------------
def test_change_password_flow(client, admin):
    user, data = session_for(client, admin)
    h = hdr(data["access_token"])
    assert client.post("/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": NEW_PW}).status_code == 401
    assert client.post("/auth/change-password", headers=h, json={"current_password": GOOD_PW, "new_password": "short1"}).status_code == 422
    assert client.post("/auth/change-password", headers=h, json={"current_password": GOOD_PW, "new_password": GOOD_PW}).status_code == 422

    time.sleep(1.1)  # token `iat` has one-second resolution
    assert client.post("/auth/change-password", headers=h, json={"current_password": GOOD_PW, "new_password": NEW_PW}).status_code == 204

    assert login(client, user["username"], GOOD_PW).status_code == 401
    assert login(client, user["username"], NEW_PW).status_code == 200
    assert client.get("/api/me", headers=h).status_code == 401  # tokens issued before the change are dead
    assert client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_admin_reset_password_signs_user_out(client, admin):
    user, data = session_for(client, admin)
    time.sleep(1.1)
    assert client.post(f"/api/users/{user['id']}/reset-password", headers=admin, json={"new_password": "weak"}).status_code == 422
    assert client.post(f"/api/users/{user['id']}/reset-password", headers=admin, json={"new_password": NEW_PW}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401
    assert client.get("/api/me", headers=hdr(data["access_token"])).status_code == 401
    assert login(client, user["username"], NEW_PW).status_code == 200


# ---------------- authorization (access levels and permissions) ----------------
def test_roles_expose_levels_and_permissions(client, hannah):
    roles = {r["name"]: r for r in client.get("/api/roles", headers=hannah).json()}
    assert [roles[n]["level"] for n in ("employee", "manager", "hr", "admin")] == [10, 20, 30, 100]
    assert "users:manage" in roles["admin"]["permissions"] and "users:manage" not in roles["hr"]["permissions"]


def test_permission_matrix(client, alice, hannah, carl, admin):
    # (method, path, expected status per caller: alice, hannah, carl, admin)
    matrix = [
        ("get", "/api/users", (403, 200, 200, 200)),
        ("get", "/api/roles", (403, 200, 200, 200)),
        ("get", "/api/audit-log", (403, 403, 200, 200)),
        ("get", "/api/documents", (403, 200, 200, 200)),
    ]
    for method, path, expected in matrix:
        got = tuple(getattr(client, method)(path, headers=h).status_code for h in (alice, hannah, carl, admin))
        assert got == expected, (path, got)
    body = {"username": "x" + uuid.uuid4().hex[:6], "password": GOOD_PW, "full_name": "X"}
    assert tuple(client.post("/api/users", headers=h, json=body).status_code for h in (alice, hannah, carl)) == (403, 403, 403)


def test_unauthenticated_requests_get_401_not_403(client):
    for path in ("/api/users", "/api/roles", "/api/audit-log", "/api/documents", "/api/models"):
        assert client.get(path).status_code == 401, path


def test_role_change_applies_immediately_without_relogin(client, admin):
    user, data = session_for(client, admin)
    h = hdr(data["access_token"])
    assert client.get("/api/documents", headers=h).status_code == 403
    assert client.patch(f"/api/users/{user['id']}", headers=admin, json={"role": "hr"}).json()["role"] == "hr"
    assert client.get("/api/documents", headers=h).status_code == 200  # same token, new access level
    client.patch(f"/api/users/{user['id']}", headers=admin, json={"role": "employee"})
    assert client.get("/api/documents", headers=h).status_code == 403


def test_deactivation_kills_existing_sessions(client, admin):
    user, data = session_for(client, admin)
    r = client.delete(f"/api/users/{user['id']}", headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/me", headers=hdr(data["access_token"])).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401
    assert login(client, user["username"], GOOD_PW).status_code == 403
    assert client.get(f"/api/users/{user['id']}", headers=admin).status_code == 200  # soft delete keeps the record
    reactivated = client.patch(f"/api/users/{user['id']}", headers=admin, json={"is_active": True})
    assert reactivated.json()["is_active"] is True and login(client, user["username"], GOOD_PW).status_code == 200


def test_admin_cannot_lock_themselves_out(client, admin):
    me = client.get("/api/me", headers=admin).json()
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"role": "employee"}).status_code == 403
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"is_active": False}).status_code == 403
    assert client.delete(f"/api/users/{me['id']}", headers=admin).status_code == 403
    assert client.patch(f"/api/users/{me['id']}", headers=admin, json={"department": "IT"}).status_code == 200


# ---------------- user administration ----------------
def test_create_user_validation(client, admin):
    ok = make_user(client, admin, department="Sales")
    assert ok["role"] == "employee" and ok["level"] == 10 and "password" not in ok and "password_hash" not in ok
    base = {"password": GOOD_PW, "full_name": "Z"}
    u = "v" + uuid.uuid4().hex[:6]
    cases = [
        ({"username": u, "password": "short1"}, 422),
        ({"username": u, "password": "alllettersnodigits"}, 422),
        ({"username": u, "role": "wizard"}, 422),
        ({"username": "Bad Name!"}, 422),
        ({"username": ok["username"]}, 409),
        ({"username": u, "email": "not-an-email"}, 422),
        ({"username": u, "manager_id": str(uuid.uuid4())}, 404),
    ]
    for override, expected in cases:
        assert client.post("/api/users", headers=admin, json={**base, **override}).status_code == expected, override


def test_duplicate_email_conflict(client, admin):
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    make_user(client, admin, email=email)
    body = {"username": "d" + uuid.uuid4().hex[:6], "password": GOOD_PW, "full_name": "D", "email": email.upper()}
    assert client.post("/api/users", headers=admin, json=body).status_code == 409


def test_manager_rules(client, admin):
    boss, mid, low = (make_user(client, admin) for _ in range(3))
    assert client.patch(f"/api/users/{mid['id']}", headers=admin, json={"manager_id": boss["id"]}).status_code == 200
    assert client.patch(f"/api/users/{low['id']}", headers=admin, json={"manager_id": mid["id"]}).json()["manager_id"] == mid["id"]
    assert client.patch(f"/api/users/{boss['id']}", headers=admin, json={"manager_id": low["id"]}).status_code == 422  # cycle
    assert client.patch(f"/api/users/{boss['id']}", headers=admin, json={"manager_id": boss["id"]}).status_code == 422  # self
    assert client.patch(f"/api/users/{low['id']}", headers=admin, json={"manager_id": None}).json()["manager_id"] is None  # clear


def test_list_users_filters_and_pagination(client, admin):
    tag = uuid.uuid4().hex[:6]
    for i in range(3):
        make_user(client, admin, role="manager", department="QA", full_name=f"Zed {tag} {i}")
    page = client.get("/api/users", headers=admin, params={"q": tag, "limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["limit"] == 2
    rest = client.get("/api/users", headers=admin, params={"q": tag, "limit": 2, "offset": 2}).json()
    assert len(rest["items"]) == 1
    assert client.get("/api/users", headers=admin, params={"q": tag, "role": "hr"}).json()["total"] == 0
    assert client.get("/api/users", headers=admin, params={"limit": 0}).status_code == 422


def test_get_unknown_or_malformed_user(client, admin):
    assert client.get(f"/api/users/{uuid.uuid4()}", headers=admin).status_code == 404
    assert client.get("/api/users/not-a-uuid", headers=admin).status_code == 422


# ---------------- audit ----------------
def test_audit_log_records_security_events(client, admin, carl):
    user = make_user(client, admin)
    login(client, user["username"], "wrong-password-1")
    login(client, user["username"], GOOD_PW)
    client.patch(f"/api/users/{user['id']}", headers=admin, json={"department": "Ops"})
    log = client.get("/api/audit-log", headers=carl, params={"username": user["username"]}).json()["items"]
    by_action = {(e["action"], e["success"]) for e in log}
    assert ("login", False) in by_action and ("login", True) in by_action
    failed = next(e for e in log if e["action"] == "login" and not e["success"])
    assert failed["detail"] == {"reason": "bad_password"} and failed["ip_address"]
    admin_events = client.get("/api/audit-log", headers=carl, params={"action": "user_update"}).json()["items"]
    assert any(e["detail"]["target"] == user["username"] and e["detail"]["changes"] == {"department": "Ops"} for e in admin_events)
    assert "password" not in str(admin_events).lower().replace("password_reset", "")  # no secrets in the log
