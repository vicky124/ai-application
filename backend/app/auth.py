"""Demo authentication: fixed users, JWT with role claims. Swap for OIDC later."""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings

ROLES = ("employee", "manager", "hr", "compliance", "admin")

# Roles that may read each document tier. Documents list allowed roles in payload;
# "employee" docs are visible to everyone.
DEMO_USERS = {
    "alice": {"password": "alice123", "name": "Alice Employee", "role": "employee", "department": "Engineering"},
    "mark": {"password": "mark123", "name": "Mark Manager", "role": "manager", "department": "Engineering"},
    "hannah": {"password": "hannah123", "name": "Hannah HR", "role": "hr", "department": "HR"},
    "carl": {"password": "carl123", "name": "Carl Compliance", "role": "compliance", "department": "Legal"},
    "root": {"password": "root123", "name": "Admin", "role": "admin", "department": "IT"},
}

bearer = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: str
    name: str
    role: str
    department: str


def create_token(user_id: str) -> str:
    u = DEMO_USERS[user_id]
    payload = {
        "sub": user_id,
        "name": u["name"],
        "role": u["role"],
        "department": u["department"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def authenticate(username: str, password: str) -> str | None:
    u = DEMO_USERS.get(username)
    if u and u["password"] == password:
        return create_token(username)
    return None


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        data = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return User(id=data["sub"], name=data["name"], role=data["role"], department=data["department"])


def require_roles(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return checker
