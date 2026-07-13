"""Password hashing and JWT primitives for curator authentication."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from course_platform.config import Settings
from course_platform.models.enums import StaffRole

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "course-platform"
password_hash = PasswordHash.recommended()


class JWTConfigurationError(RuntimeError):
    pass


class InvalidAccessTokenError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    staff_id: UUID
    role: StaffRole


@dataclass(frozen=True, slots=True)
class AttachmentMediaTokenClaims:
    staff_id: UUID
    submission_id: UUID
    attachment_id: UUID


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(password, stored_hash)
    except UnknownHashError:
        return False


def create_access_token(
    *,
    staff_id: UUID,
    role: StaffRole,
    settings: Settings,
) -> str:
    if settings.jwt_secret is None:
        raise JWTConfigurationError("JWT_SECRET is not configured")

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    return jwt.encode(
        {
            "sub": str(staff_id),
            "role": role.value,
            "iat": now,
            "exp": expires_at,
            "iss": JWT_ISSUER,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    if settings.jwt_secret is None:
        raise JWTConfigurationError("JWT_SECRET is not configured")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
        return AccessTokenClaims(
            staff_id=UUID(payload["sub"]),
            role=StaffRole(payload["role"]),
        )
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise InvalidAccessTokenError from None


def create_attachment_media_token(
    *,
    staff_id: UUID,
    submission_id: UUID,
    attachment_id: UUID,
    settings: Settings,
    expires_in_seconds: int = 1800,
) -> str:
    """Create a short-lived URL token for one protected Telegram attachment."""

    if settings.jwt_secret is None:
        raise JWTConfigurationError("JWT_SECRET is not configured")

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(staff_id),
            "submission_id": str(submission_id),
            "attachment_id": str(attachment_id),
            "purpose": "attachment_media",
            "iat": now,
            "exp": now + timedelta(seconds=expires_in_seconds),
            "iss": JWT_ISSUER,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )


def decode_attachment_media_token(
    token: str,
    settings: Settings,
) -> AttachmentMediaTokenClaims:
    if settings.jwt_secret is None:
        raise JWTConfigurationError("JWT_SECRET is not configured")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
        if payload["purpose"] != "attachment_media":
            raise InvalidAccessTokenError
        return AttachmentMediaTokenClaims(
            staff_id=UUID(payload["sub"]),
            submission_id=UUID(payload["submission_id"]),
            attachment_id=UUID(payload["attachment_id"]),
        )
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise InvalidAccessTokenError from None
