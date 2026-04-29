"""Tests for the PII redactor.

Negative tests here are red-line 3 critical: every key in the deny set
must redact, no key outside it must redact. A regression here is a PII
leak in prod logs.
"""
from __future__ import annotations

import json

import pytest

from app.core.observability import (
    DENY_KEYS,
    _is_sensitive_key,
    redact,
    redact_json,
)


@pytest.mark.parametrize(
    "key,expected",
    [
        ("email", True),
        ("Email", True),
        ("EMAIL", True),
        ("password", True),
        ("Authorization", True),
        ("authorization", True),
        ("Cookie", True),
        ("set-cookie", True),     # split on '-'
        ("access_token", True),    # split on '_' → 'access','token'
        ("id_token", True),
        ("refresh_token", True),
        ("customer_email", True),  # contains 'email'
        ("user_phone", True),
        ("emailAddress", True),    # CamelCase split → 'email','Address'
        ("pii_salt", True),
        ("name", False),
        ("user_id", False),
        ("display_name", False),
        ("count", False),
        ("status_code", False),     # ``code`` not in deny set
        ("duration_ms", False),
        ("confirmation_code", False),  # ``code`` not in deny set
        ("secrets_count", False),   # plural ``secrets`` != ``secret``;
                                    # this is the conservative side of
                                    # the trade-off — DENY_KEYS holds
                                    # exact fragments, not stems
        ("otp_code", True),         # ``otp`` matches; verification codes
                                    # MUST be logged under this key
    ],
)
def test_is_sensitive_key(key: str, expected: bool) -> None:
    assert _is_sensitive_key(key) is expected


def test_redact_replaces_top_level_deny_keys() -> None:
    out = redact({"email": "alice@example.com", "name": "Alice"})
    assert out == {"email": "[REDACTED]", "name": "Alice"}


def test_redact_recurses_into_nested_dicts() -> None:
    out = redact(
        {
            "user": {
                "email": "alice@example.com",
                "profile": {"phone": "+15555550100", "name": "Alice"},
            },
            "request_id": "01ABC",
        }
    )
    assert out == {
        "user": {
            "email": "[REDACTED]",
            "profile": {"phone": "[REDACTED]", "name": "Alice"},
        },
        "request_id": "01ABC",
    }


def test_redact_recurses_into_lists() -> None:
    out = redact(
        {
            "members": [
                {"email": "a@x.com", "name": "A"},
                {"email": "b@x.com", "name": "B"},
            ]
        }
    )
    assert out["members"][0]["email"] == "[REDACTED]"
    assert out["members"][1]["email"] == "[REDACTED]"
    assert out["members"][0]["name"] == "A"


def test_redact_handles_pii_salt_key() -> None:
    out = redact({"pii_salt": "deadbeef" * 8, "users_table_name": "X"})
    assert out["pii_salt"] == "[REDACTED]"
    assert out["users_table_name"] == "X"


def test_redact_passes_through_non_dict_non_list() -> None:
    assert redact("hello") == "hello"
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(True) is True


def test_is_sensitive_key_handles_non_string() -> None:
    """If a dict happens to use non-string keys (rare in JSON-shaped logs
    but legal in Python), the redactor must not crash — it returns
    False (the value can't have leaked a secret if its key isn't a name)."""
    assert _is_sensitive_key(42) is False
    assert _is_sensitive_key(None) is False
    assert _is_sensitive_key(("compound", "key")) is False


def test_redact_handles_empty_inputs() -> None:
    assert redact({}) == {}
    assert redact([]) == []


def test_redact_json_round_trip() -> None:
    payload = '{"email": "a@b.com", "name": "Alice"}'
    out = redact_json(payload)
    parsed = json.loads(out)
    assert parsed == {"email": "[REDACTED]", "name": "Alice"}


def test_redact_json_falls_back_safely_on_invalid_json() -> None:
    """Non-JSON input must not be returned verbatim — that's how raw
    request bodies leak. The safe default is to redact the whole thing."""
    assert redact_json("not-json-at-all") == "[REDACTED]"
    assert redact_json("password=hunter2") == "[REDACTED]"


def test_deny_keys_contains_critical_pii_terms() -> None:
    """Sanity check that the deny set hasn't been accidentally stripped."""
    must_have = {"email", "phone", "password", "token", "salt"}
    assert must_have.issubset(DENY_KEYS), (
        f"DENY_KEYS missing critical terms: {must_have - DENY_KEYS}"
    )
