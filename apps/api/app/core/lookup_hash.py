"""Email lookup hash.

HMAC-SHA-256 keyed on the per-environment salt loaded from
``/contricool/<env>/pii-salt`` via ``app.core.config.load()``. Output is
the bare 64-char hex digest — callers prefix it with ``EMAIL#`` (or any
other key prefix) before writing to DynamoDB.

The salt never rotates (rotation invalidates every existing user's lookup
row). See ``specs/13-privacy-pii/design.md`` and
``specs/07-database-data-model/design.md`` §"Email lookup (privacy)".
"""
from __future__ import annotations

import hashlib
import hmac

from app.core import config


def email_hash(email: str) -> str:
    """Return ``HMAC-SHA-256(salt, lower(strip(email)))`` as 64-char hex."""
    if not isinstance(email, str):
        raise ValueError("email must be a string")
    normalised = email.strip().lower()
    if not normalised:
        raise ValueError("email must be non-empty after stripping whitespace")
    salt = config.load().pii_salt.encode("utf-8")
    return hmac.new(salt, normalised.encode("utf-8"), hashlib.sha256).hexdigest()
