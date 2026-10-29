"""Request/response models for the auth and user-management REST API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"


class CurrentUser(BaseModel):
    """The authenticated caller, rebuilt from the database on every request."""

    id: str
    username: str
    name: str
    role: str
    level: int
    department: str
    permissions: list[str]

    def can(self, *codes: str) -> bool:
        return all(c in self.permissions for c in codes)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str | None
    name: str
    role: str
    level: int
    department: str
    manager_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: CurrentUser


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    role: str = "employee"
    department: str = Field(default="General", max_length=80)
    manager_id: uuid.UUID | None = None

    @field_validator("username", mode="before")
    @classmethod
    def lowercase(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class UserUpdate(BaseModel):
    """PATCH semantics: only fields present in the request body are changed (null clears manager/email)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    role: str | None = None
    department: str | None = Field(default=None, max_length=80)
    manager_id: uuid.UUID | None = None
    is_active: bool | None = None


class RoleOut(BaseModel):
    name: str
    level: int
    description: str
    permissions: list[str]


class Page(BaseModel):
    total: int
    offset: int
    limit: int


class UserPage(Page):
    items: list[UserOut]


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    action: str
    success: bool
    username: str | None
    user_id: uuid.UUID | None
    ip_address: str | None
    detail: dict | None


class AuditPage(Page):
    items: list[AuditOut]
