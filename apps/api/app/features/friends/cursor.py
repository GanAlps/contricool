"""Opaque, HMAC-signed pagination cursors for ``GET /v1/friends``.

A cursor encodes one piece of state — the user_id of the last friend
returned on the previous page — and binds it to the **requester's**
user_id at issue time. A cursor minted for User A presented by User
B is rejected with :class:`InvalidCursorError`.

Format::

    base64url( "<requester_id>:<last_friend_id>" "." hex(hmac_sha256(payload)) )

The signing key is the per-environment ``pii-salt`` SecureString (the
same key used by :mod:`app.core.lookup_hash` for the email lookup
hash). Re-using the salt avoids a second SSM parameter and a second
IAM grant — the cursor isn't a secret, just tamper-evident.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from app.core import config


class InvalidCursorError(Exception):
    """Raised when a cursor is malformed, tampered with, or bound to a
    different requester."""


_SEPARATOR = "."


def _signing_key() -> bytes:
    return config.load().pii_salt.encode("utf-8")


def _sign(payload: str) -> str:
    return hmac.new(_signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64url_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> str:
    # Re-pad the urlsafe base64 input — Python's decoder requires it.
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError("malformed cursor") from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCursorError("malformed cursor") from exc


def encode(*, requester_id: str, last_friend_id: str) -> str:
    """Mint a cursor for ``requester_id`` pointing at ``last_friend_id``."""
    if not requester_id or not last_friend_id:
        raise ValueError("requester_id and last_friend_id must be non-empty")
    payload = f"{requester_id}:{last_friend_id}"
    sig = _sign(payload)
    return _b64url_encode(f"{payload}{_SEPARATOR}{sig}")


def decode(*, cursor: str, requester_id: str) -> str:
    """Return ``last_friend_id`` for a cursor minted for ``requester_id``.

    Raises :class:`InvalidCursorError` on any of:

    - malformed base64 / non-utf8 bytes,
    - missing separator,
    - HMAC mismatch (tampered cursor),
    - cursor minted for a different requester.
    """
    if not cursor:
        raise InvalidCursorError("empty cursor")
    decoded = _b64url_decode(cursor)
    if _SEPARATOR not in decoded:
        raise InvalidCursorError("malformed cursor")
    payload, sig = decoded.rsplit(_SEPARATOR, 1)
    expected_sig = _sign(payload)
    if not hmac.compare_digest(sig, expected_sig):
        raise InvalidCursorError("cursor signature mismatch")
    if ":" not in payload:
        raise InvalidCursorError("malformed cursor payload")
    cursor_requester, last_friend_id = payload.split(":", 1)
    if cursor_requester != requester_id:
        raise InvalidCursorError("cursor bound to a different requester")
    if not last_friend_id:
        raise InvalidCursorError("malformed cursor payload")
    return last_friend_id
