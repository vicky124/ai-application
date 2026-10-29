"""Authentication and user-administration use cases. Framework-free: they raise ServiceError subclasses and
own the transaction boundary (commit). Collaborators are injected, so each can be replaced independently."""
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import errors
from app.auth.passwords import PasswordHasher, password_problems
from app.auth.repositories import AuditRepository, RefreshTokenRepository, RoleRepository, UserRepository
from app.auth.schemas import CurrentUser, TokenResponse, UserCreate, UserOut
from app.auth.tokens import TokenService, hash_refresh_token, new_refresh_token
from app.db.models import RefreshToken, User, utcnow


@dataclass(frozen=True)
class AuthPolicy:
    max_failed_logins: int
    lockout_minutes: int
    refresh_token_days: int
    password_min_length: int


def to_current_user(user: User) -> CurrentUser:
    return CurrentUser(
        id=str(user.id),
        username=user.username,
        name=user.full_name,
        role=user.role.name,
        level=user.role.level,
        department=user.department,
        permissions=user.permission_codes,
    )


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        name=user.full_name,
        role=user.role.name,
        level=user.role.level,
        department=user.department,
        manager_id=user.manager_id,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


class AuthService:
    def __init__(
        self,
        session: Session,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuditRepository,
        hasher: PasswordHasher,
        tokens: TokenService,
        policy: AuthPolicy,
    ):
        self._s, self._users, self._rt, self._audit = session, users, refresh_tokens, audit
        self._hasher, self._tokens, self._policy = hasher, tokens, policy

    # ---- login / refresh / logout ----
    def login(self, username: str, password: str, ip: str | None = None, user_agent: str | None = None) -> TokenResponse:
        uname = username.strip().lower()
        user = self._users.by_username(uname)
        now = utcnow()

        if user is None:
            self._hasher.verify(self._dummy_hash(), password)  # equalize timing with the real path
            self._fail("login", None, uname, ip, "unknown_user")
            raise errors.InvalidCredentials("Invalid username or password")

        if user.locked_until and user.locked_until > now:
            self._fail("login", user, uname, ip, "locked")
            raise errors.AccountLocked("Too many failed attempts. Try again later.")

        if not self._hasher.verify(user.password_hash, password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= self._policy.max_failed_logins:
                user.locked_until = now + timedelta(minutes=self._policy.lockout_minutes)
                user.failed_login_attempts = 0
                self._audit.add("account_locked", False, user.id, uname, ip, {"minutes": self._policy.lockout_minutes})
            self._fail("login", user, uname, ip, "bad_password")
            raise errors.InvalidCredentials("Invalid username or password")

        if not user.is_active:
            self._fail("login", user, uname, ip, "disabled")
            raise errors.AccountDisabled("Account is disabled")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = now
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(password)
        response = self._issue(user, uuid.uuid4(), ip, user_agent)
        self._audit.add("login", True, user.id, uname, ip)
        self._s.commit()
        return response

    def refresh(self, raw_token: str, ip: str | None = None, user_agent: str | None = None) -> TokenResponse:
        row = self._rt.by_hash(hash_refresh_token(raw_token))
        now = utcnow()
        if row is None:
            raise errors.InvalidToken("Invalid refresh token")
        if row.revoked_at is not None:
            # A rotated/revoked token is being replayed: assume theft and kill the whole chain.
            self._rt.revoke_family(row.family_id, now)
            self._audit.add("refresh_reuse_detected", False, row.user_id, row.user.username, ip)
            self._s.commit()
            raise errors.InvalidToken("Invalid refresh token")
        if row.expires_at <= now or not row.user.is_active:
            raise errors.InvalidToken("Invalid refresh token")

        row.revoked_at = now  # single use: rotate
        response = self._issue(row.user, row.family_id, ip, user_agent)
        self._audit.add("refresh", True, row.user_id, row.user.username, ip)
        self._s.commit()
        return response

    def logout(self, raw_token: str, ip: str | None = None) -> None:
        """Idempotent: unknown tokens are ignored."""
        row = self._rt.by_hash(hash_refresh_token(raw_token))
        if row is not None:
            self._rt.revoke_family(row.family_id, utcnow())
            self._audit.add("logout", True, row.user_id, row.user.username, ip)
            self._s.commit()

    def logout_all(self, user: CurrentUser, ip: str | None = None) -> None:
        uid = uuid.UUID(user.id)
        self._rt.revoke_all_for_user(uid, utcnow())
        self._audit.add("logout_all", True, uid, user.username, ip)
        self._s.commit()

    def change_password(self, current: CurrentUser, old_password: str, new_password: str, ip: str | None = None) -> None:
        user = self._users.get(uuid.UUID(current.id))
        if user is None or not self._hasher.verify(user.password_hash, old_password):
            self._audit.add("password_change", False, uuid.UUID(current.id), current.username, ip, {"reason": "bad_current_password"})
            self._s.commit()
            raise errors.InvalidCredentials("Current password is incorrect")
        problems = password_problems(new_password, user.username, self._policy.password_min_length)
        if problems:
            raise errors.ValidationFailed("Password " + "; ".join(problems))
        if self._hasher.verify(user.password_hash, new_password):
            raise errors.ValidationFailed("New password must differ from the current one")
        _set_password(user, self._hasher.hash(new_password))
        self._rt.revoke_all_for_user(user.id, utcnow())  # signs out every session, including this one's refresh token
        self._audit.add("password_change", True, user.id, user.username, ip)
        self._s.commit()

    # ---- helpers ----
    def _issue(self, user: User, family_id: uuid.UUID, ip: str | None, user_agent: str | None) -> TokenResponse:
        access = self._tokens.create_access_token(user.id, user.username, user.role.name, user.role.level)
        raw, hashed = new_refresh_token()
        self._rt.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hashed,
                family_id=family_id,
                expires_at=utcnow() + timedelta(days=self._policy.refresh_token_days),
                ip_address=ip,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        return TokenResponse(
            access_token=access, refresh_token=raw, expires_in=self._tokens.access_ttl_seconds, user=to_current_user(user)
        )

    def _fail(self, action: str, user: User | None, username: str, ip: str | None, reason: str) -> None:
        self._audit.add(action, False, user.id if user else None, username, ip, {"reason": reason})
        self._s.commit()

    _dummy: str | None = None

    def _dummy_hash(self) -> str:
        if AuthService._dummy is None:
            AuthService._dummy = self._hasher.hash("timing-equalization-placeholder")
        return AuthService._dummy


def _set_password(user: User, hashed: str) -> None:
    user.password_hash = hashed
    user.password_changed_at = utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None


class UserAdminService:
    def __init__(
        self,
        session: Session,
        users: UserRepository,
        roles: RoleRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuditRepository,
        hasher: PasswordHasher,
        policy: AuthPolicy,
    ):
        self._s, self._users, self._roles, self._rt, self._audit = session, users, roles, refresh_tokens, audit
        self._hasher, self._policy = hasher, policy

    def create(self, data: UserCreate, actor: CurrentUser, ip: str | None = None) -> User:
        role = self._roles.by_name(data.role)
        if role is None:
            raise errors.ValidationFailed(f"Unknown role '{data.role}'")
        problems = password_problems(data.password, data.username, self._policy.password_min_length)
        if problems:
            raise errors.ValidationFailed("Password " + "; ".join(problems))
        if data.manager_id is not None:
            self._require_user(data.manager_id, "Manager")
        user = User(
            username=data.username,
            email=str(data.email).lower() if data.email else None,
            full_name=data.full_name,
            password_hash=self._hasher.hash(data.password),
            role_id=role.id,
            department=data.department,
            manager_id=data.manager_id,
        )
        try:
            self._users.add(user)
            self._audit.add("user_create", True, uuid.UUID(actor.id), actor.username, ip, {"target": data.username, "role": data.role})
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            raise errors.Conflict("Username or email already exists")
        self._s.refresh(user)
        return user

    def get(self, user_id: uuid.UUID) -> User:
        return self._require_user(user_id, "User")

    def search(self, query: str | None, role: str | None, active: bool | None, offset: int, limit: int):
        return self._users.search(query, role, active, offset, limit)

    def update(self, user_id: uuid.UUID, fields: dict, actor: CurrentUser, ip: str | None = None) -> User:
        user = self._require_user(user_id, "User")
        is_self = str(user.id) == actor.id
        changes: dict = {}

        if "role" in fields and fields["role"] is not None and fields["role"] != user.role.name:
            if is_self:
                raise errors.Forbidden("You cannot change your own role")
            role = self._roles.by_name(fields["role"])
            if role is None:
                raise errors.ValidationFailed(f"Unknown role '{fields['role']}'")
            changes["role"] = f"{user.role.name} -> {role.name}"
            user.role_id, user.role = role.id, role

        if "is_active" in fields and fields["is_active"] is not None and fields["is_active"] != user.is_active:
            if is_self and not fields["is_active"]:
                raise errors.Forbidden("You cannot deactivate your own account")
            user.is_active = fields["is_active"]
            changes["is_active"] = user.is_active
            if not user.is_active:
                self._rt.revoke_all_for_user(user.id, utcnow())

        if "manager_id" in fields:
            mid = fields["manager_id"]
            if mid is not None:
                self._check_manager(user, mid)
            user.manager_id = mid
            changes["manager_id"] = str(mid) if mid else None

        for key, column in (("full_name", "full_name"), ("department", "department")):
            if fields.get(key) is not None and fields[key] != getattr(user, column):
                setattr(user, column, fields[key])
                changes[key] = fields[key]
        if "email" in fields:
            email = str(fields["email"]).lower() if fields["email"] else None
            if email != user.email:
                user.email = email
                changes["email"] = email

        try:
            self._audit.add("user_update", True, uuid.UUID(actor.id), actor.username, ip, {"target": user.username, "changes": changes})
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            raise errors.Conflict("Email already in use")
        self._s.refresh(user)
        return user

    def reset_password(self, user_id: uuid.UUID, new_password: str, actor: CurrentUser, ip: str | None = None) -> None:
        user = self._require_user(user_id, "User")
        problems = password_problems(new_password, user.username, self._policy.password_min_length)
        if problems:
            raise errors.ValidationFailed("Password " + "; ".join(problems))
        _set_password(user, self._hasher.hash(new_password))
        self._rt.revoke_all_for_user(user.id, utcnow())
        self._audit.add("password_reset", True, uuid.UUID(actor.id), actor.username, ip, {"target": user.username})
        self._s.commit()

    def deactivate(self, user_id: uuid.UUID, actor: CurrentUser, ip: str | None = None) -> User:
        """Soft delete: the account is disabled and signed out, but its history and audit trail remain."""
        return self.update(user_id, {"is_active": False}, actor, ip)

    # ---- helpers ----
    def _require_user(self, user_id: uuid.UUID, label: str) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise errors.NotFound(f"{label} not found")
        return user

    def _check_manager(self, user: User, manager_id: uuid.UUID) -> None:
        if manager_id == user.id:
            raise errors.ValidationFailed("A user cannot be their own manager")
        cursor = self._require_user(manager_id, "Manager")
        for _ in range(50):  # reject cycles in the reporting chain
            if cursor.manager_id is None:
                return
            if cursor.manager_id == user.id:
                raise errors.ValidationFailed("This would create a reporting cycle")
            cursor = self._users.get(cursor.manager_id)
            if cursor is None:
                return
