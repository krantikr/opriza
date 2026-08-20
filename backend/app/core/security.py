"""Passwords, session tokens, and encryption of stored credentials.

Three separate concerns kept in one module because they share one rule: none
of them may be reimplemented at a call site. Every hash, every token and every
encrypted credential in the system goes through the functions here, so there
is one place to audit and one place to change an algorithm.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Argon2id at the library defaults, which target roughly 50ms per hash on
#: current hardware. Deliberately slow: the cost is paid once per sign-in and
#: is what makes an offline attack on a stolen database expensive.
_hasher = PasswordHasher()


# --- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Check a password, in constant time as far as the caller is concerned.

    A user with no password set (invited but not yet accepted) still pays the
    cost of a verification against a dummy hash. Returning early would let an
    unauthenticated caller distinguish "no such account" from "wrong password"
    by timing alone, which is how account lists get enumerated.
    """
    if not stored_hash:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


#: Hashed once at import so the timing-equalising path above costs the same as
#: a real verification.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-comparison")


def needs_rehash(stored_hash: str) -> bool:
    """Whether a stored hash used weaker parameters than we now use."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


# --- Session tokens --------------------------------------------------------


class TokenError(RuntimeError):
    """A token was missing, malformed, expired, or no longer valid."""


def issue_token(
    *,
    user_id: int,
    organisation_id: int | None,
    role: str,
    is_super_admin: bool,
    token_version: int,
) -> str:
    """Mint a signed access token.

    `org` is carried in the token rather than looked up per request, and is
    what `bind_session` uses. This matters: it means the organisation comes
    from something the server signed, never from a header, query parameter or
    body that a caller could set to somebody else's id.

    `ver` pins the token to the user's current `token_version`, so changing a
    password or deactivating an account invalidates every token already issued
    without needing a revocation list.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organisation_id,
        "role": role,
        "sa": is_super_admin,
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_token(token: str) -> dict[str, Any]:
    """Verify and decode a token, or raise `TokenError`.

    The algorithm is pinned to the configured one. Accepting whatever the
    token's own header claims is the classic JWT forgery: a caller sets
    `alg: none`, or swaps HS256 for RS256, and signs their own admin token.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("This session has expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("This session is not valid. Please sign in again.") from exc


# --- Invitations -----------------------------------------------------------


def new_invite_token() -> tuple[str, str]:
    """A single-use invite token and the hash to store.

    The plaintext goes in the emailed link and is never persisted; only the
    hash is stored. A leaked database therefore yields no working invitations.
    SHA-256 rather than Argon2 is appropriate here because the token is 256
    bits of randomness, not a guessable human secret.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_invite_token(token)


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(candidate: str, stored_hash: str) -> bool:
    """Compare in constant time, so a timing signal cannot recover a token."""
    return hmac.compare_digest(hash_invite_token(candidate), stored_hash)


# --- Credential encryption -------------------------------------------------


def _fernet() -> Fernet:
    """The key used to encrypt mailbox refresh tokens.

    Derived from `credential_key` when set, and otherwise from `jwt_secret` so
    development works without a second secret to manage. A real deployment
    should set `CREDENTIAL_KEY`: sharing one secret between session signing
    and credential encryption means rotating one forces rotating the other.
    """
    raw = settings.credential_key or settings.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt_credential(plaintext: str | None) -> str | None:
    """Encrypt a refresh token for storage."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str | None) -> str | None:
    """Decrypt a stored refresh token.

    Returns `None` rather than raising when the key has changed, so a rotated
    key presents as "this mailbox needs reconnecting" - which is the truth and
    is actionable - rather than as a crash in the poller.
    """
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning("A stored credential could not be decrypted; reconnection required.")
        return None


__all__ = [
    "TokenError",
    "decrypt_credential",
    "encrypt_credential",
    "hash_invite_token",
    "hash_password",
    "issue_token",
    "needs_rehash",
    "new_invite_token",
    "read_token",
    "tokens_match",
    "verify_password",
]
