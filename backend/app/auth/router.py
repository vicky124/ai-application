"""REST endpoints: /auth/* (authentication) and /api/me, /api/users, /api/roles, /api/audit-log (authorization-gated)."""
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.auth.deps import (
    client_ip,
    current_user,
    get_audit_repo,
    get_auth_service,
    get_role_repo,
    get_user_admin_service,
    require_permission,
)
from app.auth.repositories import AuditRepository, RoleRepository
from app.auth.schemas import (
    AuditOut,
    AuditPage,
    CurrentUser,
    LoginRequest,
    PasswordChange,
    PasswordReset,
    RefreshRequest,
    RoleOut,
    TokenResponse,
    UserCreate,
    UserOut,
    UserPage,
    UserUpdate,
)
from app.auth.service import AuthService, UserAdminService, to_user_out

auth_router = APIRouter(prefix="/auth", tags=["auth"])
api_router = APIRouter(prefix="/api", tags=["users"])


# ---------------- authentication ----------------
@auth_router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, svc: AuthService = Depends(get_auth_service)):
    return svc.login(body.username, body.password, client_ip(request), request.headers.get("user-agent"))


@auth_router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request, svc: AuthService = Depends(get_auth_service)):
    return svc.refresh(body.refresh_token, client_ip(request), request.headers.get("user-agent"))


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, request: Request, svc: AuthService = Depends(get_auth_service)):
    svc.logout(body.refresh_token, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(request: Request, user: CurrentUser = Depends(current_user), svc: AuthService = Depends(get_auth_service)):
    svc.logout_all(user, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange, request: Request, user: CurrentUser = Depends(current_user), svc: AuthService = Depends(get_auth_service)
):
    svc.change_password(user, body.current_password, body.new_password, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- current user ----------------
@api_router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(current_user)):
    return user


# ---------------- user administration ----------------
@api_router.get("/users", response_model=UserPage)
def list_users(
    q: str | None = Query(None, max_length=100),
    role: str | None = None,
    active: bool | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("users:read")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    items, total = svc.search(q, role, active, offset, limit)
    return UserPage(items=[to_user_out(u) for u in items], total=total, offset=offset, limit=limit)


@api_router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    return to_user_out(svc.create(body, actor, client_ip(request)))


@api_router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    _: CurrentUser = Depends(require_permission("users:read")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    return to_user_out(svc.get(user_id))


@api_router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    return to_user_out(svc.update(user_id, body.model_dump(exclude_unset=True), actor, client_ip(request)))


@api_router.delete("/users/{user_id}", response_model=UserOut)
def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    """Soft delete: disables the account and revokes its sessions. Returns the deactivated user."""
    return to_user_out(svc.deactivate(user_id, actor, client_ip(request)))


@api_router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    request: Request,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    svc: UserAdminService = Depends(get_user_admin_service),
):
    svc.reset_password(user_id, body.new_password, actor, client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@api_router.get("/roles", response_model=list[RoleOut])
def list_roles(_: CurrentUser = Depends(require_permission("users:read")), roles: RoleRepository = Depends(get_role_repo)):
    return [
        RoleOut(name=r.name, level=r.level, description=r.description, permissions=sorted(p.code for p in r.permissions))
        for r in roles.all()
    ]


@api_router.get("/audit-log", response_model=AuditPage)
def audit_log(
    action: str | None = Query(None, max_length=64),
    username: str | None = Query(None, max_length=64),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_permission("audit:read")),
    audit: AuditRepository = Depends(get_audit_repo),
):
    rows, total = audit.search(action, username, offset, limit)
    return AuditPage(
        items=[
            AuditOut(
                id=r.id, created_at=r.created_at, action=r.action, success=r.success, username=r.username,
                user_id=r.user_id, ip_address=r.ip_address, detail=r.detail,
            )
            for r in rows
        ],
        total=total, offset=offset, limit=limit,
    )
