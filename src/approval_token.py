"""
Approval Token — HMAC-based token generation and verification.

Token format: {timestamp}.{hex_hmac_sha256}
- timestamp: Unix epoch (seconds)
- hmac: HMAC-SHA256(secret, "{action}|{timestamp}")

Environment:
    APPROVAL_TOKEN_SECRET: Shared secret (required, >=32 chars recommended)
    APPROVAL_TOKEN_TTL: Token validity in seconds (default: 300 = 5 min)

P1 fix: replaces accept-any-string approval_token with cryptographic verification.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes
MIN_SECRET_LENGTH = 16

_secret: Optional[bytes] = None
_ttl: int = DEFAULT_TTL_SECONDS


def _get_secret() -> bytes:
    global _secret, _ttl
    if _secret is None:
        raw = os.environ.get("APPROVAL_TOKEN_SECRET", "")
        if not raw:
            raise ValueError(
                "APPROVAL_TOKEN_SECRET environment variable is not set. "
                "Cannot verify approval tokens."
            )
        if len(raw) < MIN_SECRET_LENGTH:
            logger.warning(
                "APPROVAL_TOKEN_SECRET is shorter than %d chars — weak secret!",
                MIN_SECRET_LENGTH,
            )
        _secret = raw.encode("utf-8")
        _ttl = int(os.environ.get("APPROVAL_TOKEN_TTL", str(DEFAULT_TTL_SECONDS)))
    return _secret


def reset_cache() -> None:
    """Reset cached secret (for testing)."""
    global _secret
    _secret = None


def generate(action: str) -> str:
    """Generate an HMAC approval token for the given action."""
    secret = _get_secret()
    timestamp = str(int(time.time()))
    message = f"{action}|{timestamp}".encode("utf-8")
    sig = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{timestamp}.{sig}"


def verify(token: str, action: str) -> Tuple[bool, str]:
    """Verify an HMAC approval token.

    Returns:
        (is_valid, reason) tuple.
    """
    if not token or "." not in token:
        return False, "Invalid token format (expected 'timestamp.hmac')"

    parts = token.split(".", 1)
    if len(parts) != 2:
        return False, "Invalid token format"

    ts_str, provided_sig = parts

    try:
        ts = int(ts_str)
    except ValueError:
        return False, "Invalid timestamp in token"

    # Check expiry
    try:
        secret = _get_secret()
    except ValueError as e:
        return False, str(e)

    now = int(time.time())
    age = now - ts
    if age < 0:
        return False, f"Token timestamp is in the future (drift={-age}s)"
    if age > _ttl:
        return False, f"Token expired ({age}s > {_ttl}s TTL)"

    # Recompute HMAC
    message = f"{action}|{ts_str}".encode("utf-8")
    expected_sig = hmac.new(secret, message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, "HMAC signature mismatch"

    return True, "OK"
