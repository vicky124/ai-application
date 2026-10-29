"""FastAPI wiring for auth: service construction and authentication/authorization dependencies."""
import uuid
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import errors
from app.auth.passwords import Argon2Hasher, PasswordHasher
from app.auth.repositories import AuditRepository, RefreshTokenRepository, RoleRepository, UserRepository
from app.auth.schemas import CurrentUser
from app.auth.service import AuthPolicy, AuthService, UserAdminService, to_current_user
from app.auth.tokens import TokenService
from app.config import settings
from app.db.session import get_session

bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    return TokenService(settings.jwt_secret, settings.jwt_issuer, settings.access_token_minutes)


@lru_cache(maxsize=1)
def get_hasher() -> PasswordHasher:
    return Argon2Hasher()


def get_policy() -> AuthPolicy:
    return AuthPolicy(
        max_failed_logins=settings.max_failed_logins,
        lockout_minutes=settings.lockout_minutes,
        refresh_token_days=settings.refresh_token_days,
        password_min_length=settings.password_min_length,
    )


def get_auth_service(
    session: Session = Depends(get_session),
    tokens: TokenService = Depends(get_token_service),
    hasher: PasswordHasher = Depends(get_hasher),
) -> AuthService:
    return AuthService(
        session, UserRepository(session), RefreshTokenRepository(session), AuditRepository(session), hasher, tokens, get_policy()
    )


def get_user_admin_service(
    session: Session = Depends(get_session), hasher: PasswordHasher = Depends(get_hasher)
) -> UserAdminService:
    return UserAdminService(
        session, UserRepository(session), RoleRepository(session), RefreshTokenRepository(session), AuditRepository(session), hasher, get_policy()
    )


def get_role_repo(session: Session = Depends(get_session)) -> RoleRepository:
    return RoleRepository(session)


def get_audit_repo(session: Session = Depends(get_session)) -> AuditRepository:
    return AuditRepository(session)


def client_ip(request: Request) -> str | None:
    # Direct peer address only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    return request.client.host if request.client else None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
    tokens: TokenService = Depends(get_token_service),
) -> CurrentUser:
    """Validates the JWT, then re-reads the user so deactivation and role changes apply immediately."""
    if creds is None:
        raise errors.InvalidToken("Missing token")
    claims = tokens.decode_access_token(creds.credentials)
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise errors.InvalidToken("Invalid token")
    user = UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise errors.InvalidToken("Invalid token")
    if claims["iat"] < int(user.password_changed_at.timestamp()):
        raise errors.InvalidToken("Token was issued before the last password change")
    return to_current_user(user)


def require_permission(*codes: str):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        missing = [c for c in codes if c not in user.permissions]
        if missing:
            raise errors.Forbidden(f"Missing permission: {', '.join(missing)}")
        return user

    return dependency


def require_level(minimum: int):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.level < minimum:
            raise errors.Forbidden("Insufficient access level")
        return user

    return dependency


def require_roles(*roles: str):
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise errors.Forbidden("Insufficient role")
        return user

    return dependency
