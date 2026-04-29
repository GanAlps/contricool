"""Tests for ``app.core.dependencies.current_principal``."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import Request

from app.core import dependencies as deps
from app.core.config import AppConfig
from app.core.dependencies import (
    UnauthenticatedError,
    current_principal,
    get_jwt_verifier,
    set_verifier_for_tests,
)
from tests._jwt_helpers import (
    DEFAULT_AUDIENCE_IDS,
    DEFAULT_ISSUER,
    base_access_claims,
    base_id_claims,
    build_verifier,
    mint_token,
)


@pytest.fixture(autouse=True)
def _reset_verifier_cache() -> Iterator[None]:
    set_verifier_for_tests(None)
    yield
    set_verifier_for_tests(None)


def _request_with_auth(header_value: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if header_value is not None:
        headers.append((b"authorization", header_value.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": headers,
        "query_string": b"",
        "raw_path": b"/x",
        "root_path": "",
        "scheme": "http",
        "server": ("test", 80),
    }
    return Request(scope)


def _call(request: Request):
    return asyncio.run(current_principal(request))


def test_happy_path_returns_principal(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    token = mint_token(base_id_claims())
    principal = _call(_request_with_auth(f"Bearer {token}"))
    assert principal.user_id == "01HK3W7QF6VMYG8XR3DQ7B5N6P"
    assert principal.email == "alice@example.com"
    assert principal.token_use == "id"


def test_access_token_in_authorization_rejected(seed_config: AppConfig) -> None:
    """Authorization carries the id token. Real Cognito access tokens
    lack ``custom:user_id`` / ``email`` / ``name`` and so cannot build
    a Principal — reject them at the auth layer with a precise reason
    rather than letting the failure surface as a downstream
    "missing claim". The two-token logout flow puts the access token
    in ``X-Cognito-Access-Token`` instead."""
    set_verifier_for_tests(build_verifier())
    token = mint_token(base_access_claims())
    with pytest.raises(UnauthenticatedError, match="id token"):
        _call(_request_with_auth(f"Bearer {token}"))


def test_missing_authorization_header_raises(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    with pytest.raises(UnauthenticatedError):
        _call(_request_with_auth(None))


def test_wrong_scheme_raises(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    with pytest.raises(UnauthenticatedError):
        _call(_request_with_auth("Basic dXNlcjpwYXNz"))


def test_empty_bearer_token_raises(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    with pytest.raises(UnauthenticatedError):
        _call(_request_with_auth("Bearer    "))


def test_invalid_token_raises_unauthenticated(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    with pytest.raises(UnauthenticatedError):
        _call(_request_with_auth("Bearer not-a-jwt"))


def test_token_without_custom_user_id_raises(seed_config: AppConfig) -> None:
    set_verifier_for_tests(build_verifier())
    claims = base_id_claims()
    del claims["custom:user_id"]
    token = mint_token(claims)
    with pytest.raises(UnauthenticatedError):
        _call(_request_with_auth(f"Bearer {token}"))


def test_get_jwt_verifier_builds_from_config_first_time(seed_config: AppConfig) -> None:
    set_verifier_for_tests(None)
    v = get_jwt_verifier()
    assert v._issuer == DEFAULT_ISSUER
    assert v._audience_ids == frozenset(DEFAULT_AUDIENCE_IDS)


def test_get_jwt_verifier_returns_cached_instance(seed_config: AppConfig) -> None:
    set_verifier_for_tests(None)
    v1 = get_jwt_verifier()
    v2 = get_jwt_verifier()
    assert v1 is v2


def test_set_verifier_for_tests_clears_cache(seed_config: AppConfig) -> None:
    set_verifier_for_tests(None)
    v1 = get_jwt_verifier()
    set_verifier_for_tests(None)
    v2 = get_jwt_verifier()
    assert v1 is not v2  # rebuilt after cache clear


def test_module_lock_exists() -> None:
    assert deps._lock is not None
