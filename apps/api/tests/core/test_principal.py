"""Tests for ``Principal.from_claims``."""
from __future__ import annotations

import pytest

from app.core.principal import Principal

_VALID_CLAIMS: dict[str, object] = {
    "custom:user_id": "01HK3W7QF6VMYG8XR3DQ7B5N6P",  # 26-char ULID
    "email": "alice@example.com",
    "name": "Alice Anderson",
    "token_use": "id",
    "cognito:groups": ["users"],
}


def test_from_claims_happy_path() -> None:
    p = Principal.from_claims(_VALID_CLAIMS)
    assert p.user_id == "01HK3W7QF6VMYG8XR3DQ7B5N6P"
    assert p.email == "alice@example.com"
    assert p.display_name == "Alice Anderson"
    assert p.groups == ["users"]
    assert p.token_use == "id"


def test_from_claims_missing_user_id_raises() -> None:
    claims = {k: v for k, v in _VALID_CLAIMS.items() if k != "custom:user_id"}
    with pytest.raises(ValueError, match="custom:user_id"):
        Principal.from_claims(claims)


def test_from_claims_empty_email_raises() -> None:
    claims = {**_VALID_CLAIMS, "email": ""}
    with pytest.raises(ValueError):
        Principal.from_claims(claims)


def test_from_claims_invalid_email_raises() -> None:
    claims = {**_VALID_CLAIMS, "email": "not-an-email"}
    with pytest.raises(ValueError):
        Principal.from_claims(claims)


def test_from_claims_invalid_token_use_raises() -> None:
    claims = {**_VALID_CLAIMS, "token_use": "bogus"}
    with pytest.raises(ValueError):
        Principal.from_claims(claims)


def test_from_claims_groups_default_empty_list() -> None:
    claims = {k: v for k, v in _VALID_CLAIMS.items() if k != "cognito:groups"}
    p = Principal.from_claims(claims)
    assert p.groups == []


def test_from_claims_groups_from_comma_string() -> None:
    """Some Cognito triggers emit cognito:groups as 'a,b' — accept both."""
    claims = {**_VALID_CLAIMS, "cognito:groups": "users,admins"}
    p = Principal.from_claims(claims)
    assert p.groups == ["users", "admins"]


def test_from_claims_user_id_too_short_raises() -> None:
    claims = {**_VALID_CLAIMS, "custom:user_id": "tooshort"}
    with pytest.raises(ValueError):
        Principal.from_claims(claims)


def test_from_claims_strips_whitespace() -> None:
    claims = {
        **_VALID_CLAIMS,
        "custom:user_id": "  01HK3W7QF6VMYG8XR3DQ7B5N6P  ",
        "email": "  alice@example.com  ",
        "name": "  Alice Anderson  ",
    }
    p = Principal.from_claims(claims)
    assert p.user_id == "01HK3W7QF6VMYG8XR3DQ7B5N6P"
    assert p.email == "alice@example.com"
    assert p.display_name == "Alice Anderson"


def test_principal_is_frozen() -> None:
    p = Principal.from_claims(_VALID_CLAIMS)
    with pytest.raises(ValueError):
        p.email = "other@example.com"  # type: ignore[misc]


def test_from_claims_invalid_groups_type_raises() -> None:
    claims = {**_VALID_CLAIMS, "cognito:groups": 42}
    with pytest.raises(ValueError):
        Principal.from_claims(claims)
