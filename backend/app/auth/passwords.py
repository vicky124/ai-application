"""Password hashing behind a small interface (swap algorithms without touching services)."""
from typing import Protocol

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, hashed: str, password: str) -> bool: ...
    def needs_rehash(self, hashed: str) -> bool: ...


class Argon2Hasher:
    def __init__(self):
        self._ph = _Argon2()

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, hashed: str, password: str) -> bool:
        try:
            return self._ph.verify(hashed, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        return self._ph.check_needs_rehash(hashed)


def password_problems(password: str, username: str, min_length: int) -> list[str]:
    """Policy for new passwords (seeded demo accounts bypass it)."""
    problems = []
    if len(password) < min_length:
        problems.append(f"must be at least {min_length} characters")
    if len(password) > 128:
        problems.append("must be at most 128 characters")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if password.isalpha() or password.isdigit():
        problems.append("must mix letters with digits or symbols")
    return problems
