"""JWT access tokens and opaque refresh tokens."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.auth.errors import InvalidToken

ALGORITHM = "HS256"


class TokenService:
    def __init__(self, secret: str, issuer: str, access_minutes: int):
        self._secret = secret
        self._issuer = issuer
        self._access = timedelta(minutes=access_minutes)

    @property
    def access_ttl_seconds(self) -> int:
        return int(self._access.total_seconds())

    def create_access_token(self, user_id: uuid.UUID, username: str, role: str, level: int) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "iss": self._issuer,
                "sub": str(user_id),
                "username": username,
                "role": role,
                "level": level,
                "type": "access",
                "jti": uuid.uuid4().hex,
                "iat": int(now.timestamp()),
                "exp": now + self._access,
            },
            self._secret,
            algorithm=ALGORITHM,
        )

    def decode_access_token(self, token: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except jwt.PyJWTError:
            raise InvalidToken("Invalid or expired token")
        if claims.get("type") != "access":
            raise InvalidToken("Invalid token type")
        return claims


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the client, sha256 hash for storage)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
