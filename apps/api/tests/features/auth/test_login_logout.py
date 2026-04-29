"""Tests for ``POST /v1/auth/login`` + ``/refresh`` + ``/logout``."""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core import dependencies as deps
from app.features.auth import cognito_client
from tests._jwt_helpers import (
    base_id_claims,
    build_verifier,
    mint_token,
)
from tests.features.auth.conftest import confirm_user

_SIGNUP = {
    "email": "alice@example.com",
    "password": "P@ssword123!",
    "name": "Alice",
    "currency": "USD",
}


def _signup_and_verify(
    auth_client: TestClient, auth_env: dict[str, object], signup: dict[str, object] = _SIGNUP
) -> None:
    auth_client.post("/v1/auth/signup", json=signup)
    confirm_user(auth_env, str(signup["email"]))
    # Trigger verify-email so the META row is written. moto's
    # confirm_sign_up no-ops on already-confirmed users in some
    # versions; if it raises, fall through.
    auth_client.post(
        "/v1/auth/verify-email",
        json={"email": signup["email"], "code": "111111"},
    )


# ---- Login ----------------------------------------------------------


def test_login_happy_path_returns_tokens_and_sets_cookie(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    _signup_and_verify(auth_client, auth_env)
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["id_token"]
    assert body["expires_in"] >= 0
    assert body["user"]["name"] == "Alice"
    assert body["user"]["currency"] == "USD"
    # Cookie attributes verified via Set-Cookie header.
    set_cookie = r.headers.get("set-cookie", "")
    assert "rt=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/v1/auth" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie.lower() or "samesite=strict" in set_cookie.lower()


def test_login_wrong_password_401_invalid_credentials(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    _signup_and_verify(auth_client, auth_env)
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": "WrongPassw0rd!"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_email_masked_as_invalid_credentials(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": "ghost@example.com", "password": "doesnt-matter"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unconfirmed_403_account_not_active(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    auth_client.post(
        "/v1/auth/signup",
        json={**_SIGNUP, "email": "pending@example.com"},
    )
    # Don't confirm.
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": "pending@example.com", "password": _SIGNUP["password"]},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ACCOUNT_NOT_ACTIVE"


def test_login_500_when_meta_row_missing(
    auth_client: TestClient,
    auth_env: dict[str, object],
    monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    """Cognito CONFIRMED but DDB has no META row — operational anomaly."""
    auth_client.post("/v1/auth/signup", json=_SIGNUP)
    confirm_user(auth_env, _SIGNUP["email"])
    # Don't call verify-email so the META row is absent.
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
    )
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"


def test_login_500_when_custom_user_id_missing(
    auth_client: TestClient,
    auth_env: dict[str, object],
    monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    """Cognito user lacks custom:user_id (operational anomaly)."""
    _signup_and_verify(auth_client, auth_env)
    from app.features.auth import service

    real_cognito = service._cognito

    class _Wrap:
        def __init__(self, c: object) -> None:
            self._c = c

        def __getattr__(self, name: str) -> object:
            return getattr(self._c, name)

        def admin_get_user(self, *, email: str) -> dict[str, str]:
            return {"Username": email, "email": email}

    monkeypatch.setattr(service, "_cognito", lambda: _Wrap(real_cognito()))
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
    )
    assert r.status_code == 500


# ---- Refresh -------------------------------------------------------


def test_refresh_no_cookie_401_missing(auth_client: TestClient) -> None:
    r = auth_client.post("/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MISSING_REFRESH_TOKEN"


def test_refresh_bad_cookie_401_clears_cookie(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post(
        "/v1/auth/refresh", cookies={"rt": "tampered-token-value"}
    )
    assert r.status_code == 401
    # Cookie clear on bad refresh.
    set_cookie = r.headers.get("set-cookie", "")
    assert "rt=" in set_cookie


def test_refresh_happy_via_mock(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    fake = MagicMock(wraps=auth_env["cognito"])
    fake.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "new-access",
            "IdToken": "new-id",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post("/v1/auth/refresh", cookies={"rt": "valid-rt"})
        assert r.status_code == 200
        assert r.json() == {
            "access_token": "new-access",
            "id_token": "new-id",
            "expires_in": 3600,
        }
    finally:
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


# ---- Logout --------------------------------------------------------


def test_logout_no_auth_header_401(auth_client: TestClient) -> None:
    r = auth_client.post("/v1/auth/logout")
    assert r.status_code == 401


def test_logout_tampered_token_401(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    # Install a verifier that knows about a synthetic test pool;
    # any token signed by something else fails verification.
    deps.set_verifier_for_tests(build_verifier())
    try:
        r = auth_client.post(
            "/v1/auth/logout", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    finally:
        deps.set_verifier_for_tests(None)


def test_logout_happy_via_mock(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Logout: forge a Cognito-shaped JWT signed by the test key, install
    a verifier that resolves to the test public key, then mock
    GlobalSignOut so it doesn't bark at the synthetic access token."""
    deps.set_verifier_for_tests(build_verifier())
    # Build a MagicMock that delegates non-stubbed methods to the moto
    # client but explicitly stubs global_sign_out so a synthetic test
    # access token doesn't trip moto's NotAuthorizedException.
    fake = MagicMock()
    fake.global_sign_out.return_value = None
    cognito_client._set_client_for_tests(fake)
    try:
        token = mint_token(base_id_claims())
        r = auth_client.post(
            "/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 204
        # Cookie cleared.
        assert "rt=" in r.headers.get("set-cookie", "")
        fake.global_sign_out.assert_called_once()
    finally:
        deps.set_verifier_for_tests(None)
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


def test_logout_token_from_different_pool_401(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Token claims a different issuer → verifier rejects → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        token = mint_token(
            base_id_claims(iss="https://cognito-idp.us-west-2.amazonaws.com/us-west-2_OTHER")
        )
        r = auth_client.post(
            "/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
    finally:
        deps.set_verifier_for_tests(None)
