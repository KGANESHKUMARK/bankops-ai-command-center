"""Password hashing (Argon2id) and short-lived signed access tokens (JWT)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings, resolve_jwt_secret

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
# Pre-computed hash used to equalize timing when a username does not exist.
_DUMMY_HASH = _hasher.hash(uuid.uuid4().hex)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    tenant_id: str
    role: str
    jti: str
    expires_at: datetime


class TokenError(Exception):
    """Raised for any invalid, expired or malformed token (message is safe to return)."""


def create_access_token(settings: Settings, *, user_id: str, tenant_id: str, role: str) -> tuple[str, TokenClaims]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "typ": "access",
    }
    token = jwt.encode(payload, resolve_jwt_secret(settings), algorithm=settings.jwt_algorithm)
    return token, TokenClaims(user_id=user_id, tenant_id=tenant_id, role=role, jti=jti, expires_at=expires)


def decode_access_token(settings: Settings, token: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            resolve_jwt_secret(settings),
            algorithms=[settings.jwt_algorithm],  # explicit allowlist; never "none"
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "nbf", "sub", "jti", "iss", "aud"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc
    if payload.get("typ") != "access" or not isinstance(payload.get("tid"), str):
        raise TokenError("Invalid token")
    return TokenClaims(
        user_id=str(payload["sub"]),
        tenant_id=payload["tid"],
        role=str(payload.get("role")),
        jti=str(payload["jti"]),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
    )
