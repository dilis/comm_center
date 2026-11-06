"""Password hashing and JWT creation/validation. Pure functions, no database access."""

import time
import uuid
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import settings

MIN_PASSWORD_LENGTH = 10
ALGORITHM = "HS256"
TokenKind = Literal["access", "refresh"]

_hasher = PasswordHasher()
# Verified against when a username does not exist, so login timing does not reveal valid names.
DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


class TokenError(Exception):
    """The token is malformed, expired, forged or of the wrong kind."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user_id: int, kind: TokenKind, ttl_seconds: int) -> tuple[str, str]:
    """Return ``(token, jti)``."""
    now = int(time.time())
    jti = uuid.uuid4().hex
    claims = {"sub": str(user_id), "typ": kind, "iat": now, "exp": now + ttl_seconds, "jti": jti}
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM), jti


def decode_token(token: str, kind: TokenKind) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub", "typ", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if claims["typ"] != kind:
        raise TokenError("wrong token type")
    return claims
