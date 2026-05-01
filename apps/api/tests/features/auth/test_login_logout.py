"""Tests for ``POST /v1/auth/login`` + ``/refresh`` + ``/logout``."""
from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core import dependencies as deps
from app.features.auth import cognito_client
from tests._jwt_helpers import (
    base_access_claims,
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
    assert r.json()["error"]["code"] == "REFRESH_FAILED"
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
    """Logout: ``Authorization`` carries the id token (principal),
    ``X-Cognito-Access-Token`` carries the access token (GlobalSignOut).
    GlobalSignOut is mocked so a synthetic test access token doesn't
    trip moto's NotAuthorizedException."""
    deps.set_verifier_for_tests(build_verifier())
    fake = MagicMock()
    fake.global_sign_out.return_value = None
    cognito_client._set_client_for_tests(fake)
    try:
        id_token = mint_token(base_id_claims())
        access_token_value = "raw-access-token-from-cognito"
        r = auth_client.post(
            "/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {id_token}",
                "X-Cognito-Access-Token": access_token_value,
            },
        )
        assert r.status_code == 204
        # Cookie cleared.
        assert "rt=" in r.headers.get("set-cookie", "")
        # Service forwarded the *access* token (from the new header), not
        # the id token, to GlobalSignOut.
        fake.global_sign_out.assert_called_once_with(AccessToken=access_token_value)
    finally:
        deps.set_verifier_for_tests(None)
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


def test_logout_missing_access_token_header_400(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """A valid id token but no ``X-Cognito-Access-Token`` is a malformed
    request, not an auth failure: principal is established, but we
    can't issue ``GlobalSignOut``. 400 with ``MISSING_ACCESS_TOKEN``."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        id_token = mint_token(base_id_claims())
        r = auth_client.post(
            "/v1/auth/logout", headers={"Authorization": f"Bearer {id_token}"}
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "MISSING_ACCESS_TOKEN"
        # Refresh cookie still cleared so a partial logout doesn't
        # leave a dangling session.
        assert "rt=" in r.headers.get("set-cookie", "")
    finally:
        deps.set_verifier_for_tests(None)


def test_logout_access_token_in_authorization_rejected(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """``Authorization`` must carry the id token; an access token in
    that header is 401 ``UNAUTHENTICATED``."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        access_token_jwt = mint_token(base_access_claims())
        r = auth_client.post(
            "/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {access_token_jwt}",
                "X-Cognito-Access-Token": "raw-access-token-from-cognito",
            },
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    finally:
        deps.set_verifier_for_tests(None)


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
            "/v1/auth/logout",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Cognito-Access-Token": "raw-access-token",
            },
        )
        assert r.status_code == 401
    finally:
        deps.set_verifier_for_tests(None)


# ---- Native client variants (Phase 8a) ------------------------------
#
# Native callers send ``X-Client-Platform: native`` on /v1/auth/login
# and receive the refresh token in the body for storage in
# expo-secure-store. /v1/auth/refresh accepts the refresh token from
# the body (or cookie) — body wins when both are present.


def test_login_native_returns_refresh_token_in_body_no_cookie(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    _signup_and_verify(auth_client, auth_env)
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
        headers={"X-Client-Platform": "native"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["id_token"]
    assert body["refresh_token"], "native login must return refresh_token in body"
    # No Set-Cookie for native: native clients don't carry cookies and
    # a stray Set-Cookie would only confuse intermediaries.
    assert "rt=" not in r.headers.get("set-cookie", "")


def test_login_web_default_does_not_return_refresh_token_in_body(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Without the platform header (or with a different value), refresh
    token continues to live in the HttpOnly cookie only. Returning it
    in body to web would be an XSS exfil surface."""
    _signup_and_verify(auth_client, auth_env)
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refresh_token"] is None
    assert "rt=" in r.headers.get("set-cookie", "")


def test_login_unknown_platform_treated_as_web(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Unrecognised platform values fall back to web behavior — only
    the literal ``native`` opts into the body-shape response."""
    _signup_and_verify(auth_client, auth_env)
    r = auth_client.post(
        "/v1/auth/login",
        json={"email": _SIGNUP["email"], "password": _SIGNUP["password"]},
        headers={"X-Client-Platform": "windows-phone-7"},
    )
    assert r.status_code == 200
    assert r.json()["refresh_token"] is None
    assert "rt=" in r.headers.get("set-cookie", "")


def test_refresh_via_body_happy(
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
        r = auth_client.post(
            "/v1/auth/refresh", json={"refresh_token": "valid-rt-from-body"}
        )
        assert r.status_code == 200
        assert r.json() == {
            "access_token": "new-access",
            "id_token": "new-id",
            "expires_in": 3600,
        }
    finally:
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


def test_refresh_body_wins_over_cookie(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """If a native client somehow inherits a cookie too, the body
    refresh token is still authoritative — keeps native behavior
    deterministic across edge cases."""
    fake = MagicMock(wraps=auth_env["cognito"])
    captured: dict[str, str] = {}

    def _capture(**kwargs: object) -> dict[str, dict[str, object]]:
        params = cast(dict[str, object], kwargs.get("AuthParameters", {}))
        captured["used_token"] = str(params.get("REFRESH_TOKEN", ""))
        return {
            "AuthenticationResult": {
                "AccessToken": "a",
                "IdToken": "i",
                "ExpiresIn": 3600,
                "TokenType": "Bearer",
            }
        }

    fake.initiate_auth.side_effect = _capture
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/refresh",
            json={"refresh_token": "from-body"},
            cookies={"rt": "from-cookie"},
        )
        assert r.status_code == 200
        assert captured["used_token"] == "from-body"
    finally:
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


def test_refresh_empty_body_falls_back_to_cookie(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Web clients send no body and rely on the cookie — must keep
    working unchanged after the body-path was added for native."""
    fake = MagicMock(wraps=auth_env["cognito"])
    fake.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "a",
            "IdToken": "i",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/refresh", json={"refresh_token": None}, cookies={"rt": "from-cookie"}
        )
        assert r.status_code == 200
    finally:
        cognito_client._set_client_for_tests(cast(object, auth_env["cognito"]))  # type: ignore[arg-type]


def test_refresh_no_body_no_cookie_401(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """No refresh source at all — native and web both 401."""
    r = auth_client.post("/v1/auth/refresh", json={"refresh_token": None})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MISSING_REFRESH_TOKEN"


def test_refresh_bad_body_token_401(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Body refresh that Cognito rejects → 401 REFRESH_FAILED, same as
    the cookie path (negative test parity for RED LINE 3)."""
    r = auth_client.post(
        "/v1/auth/refresh", json={"refresh_token": "tampered-body-token"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "REFRESH_FAILED"


def test_refresh_extra_body_field_rejected(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """RefreshRequest is strict — typo'd fields are 422, not silently
    ignored. Mirrors every other auth model (extra='forbid')."""
    r = auth_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": "x", "garbage_field": "should-fail"},
    )
    assert r.status_code == 422
