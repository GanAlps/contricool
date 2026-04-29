"""Tests for ``app.core.security.JwtVerifier``."""
from __future__ import annotations

import time

import pytest

from app.core.security import InvalidTokenError, JwtVerifier
from tests._jwt_helpers import (
    DEFAULT_AUDIENCE_IDS,
    DEFAULT_ISSUER,
    base_access_claims,
    base_id_claims,
    build_verifier,
    mint_token,
)


def test_verify_valid_id_token_returns_claims() -> None:
    v = build_verifier()
    token = mint_token(base_id_claims())
    claims = v.verify(token)
    assert claims["token_use"] == "id"
    assert claims["custom:user_id"] == "01HK3W7QF6VMYG8XR3DQ7B5N6P"


def test_verify_valid_access_token_returns_claims() -> None:
    v = build_verifier()
    token = mint_token(base_access_claims())
    claims = v.verify(token)
    assert claims["token_use"] == "access"
    assert claims["client_id"] == DEFAULT_AUDIENCE_IDS[0]


def test_empty_token_raises() -> None:
    v = build_verifier()
    with pytest.raises(InvalidTokenError):
        v.verify("")


def test_non_string_token_raises() -> None:
    v = build_verifier()
    with pytest.raises(InvalidTokenError):
        v.verify(None)  # type: ignore[arg-type]


def test_tampered_signature_rejected() -> None:
    v = build_verifier()
    token = mint_token(base_id_claims())
    parts = token.split(".")
    # Flip a character in the signature segment.
    sig = parts[2]
    tampered = (
        parts[0] + "." + parts[1] + "." + ("A" if sig[0] != "A" else "B") + sig[1:]
    )
    with pytest.raises(InvalidTokenError):
        v.verify(tampered)


def test_expired_token_rejected() -> None:
    v = build_verifier()
    now = int(time.time())
    token = mint_token(base_id_claims(extra={"iat": now - 7200, "exp": now - 3600}))
    with pytest.raises(InvalidTokenError):
        v.verify(token)


def test_wrong_issuer_rejected() -> None:
    v = build_verifier()
    token = mint_token(
        base_id_claims(iss="https://cognito-idp.us-west-2.amazonaws.com/us-west-2_OTHER")
    )
    with pytest.raises(InvalidTokenError):
        v.verify(token)


def test_unsupported_token_use_rejected() -> None:
    v = build_verifier()
    token = mint_token(base_id_claims(extra={"token_use": "refresh"}))
    with pytest.raises(InvalidTokenError):
        v.verify(token)


def test_id_token_with_unknown_aud_rejected() -> None:
    v = build_verifier()
    token = mint_token(base_id_claims(aud="some-other-app-client"))
    with pytest.raises(InvalidTokenError):
        v.verify(token)


def test_access_token_with_unknown_client_id_rejected() -> None:
    v = build_verifier()
    token = mint_token(base_access_claims(client_id="some-other-app-client"))
    with pytest.raises(InvalidTokenError):
        v.verify(token)


def test_jwks_lookup_failure_then_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient JWKs failure: first lookup raises, retry succeeds.

    The verifier should rebuild its ``PyJWKClient`` once and retry, not
    fail on the first hiccup.
    """
    from jwt.exceptions import PyJWKClientError

    v = build_verifier()
    saved_client = v._jwk_client  # type: ignore[attr-defined]

    class _FailOnce:
        def get_signing_key_from_jwt(self, _token: str):
            raise PyJWKClientError("kid not in cache")

    v._jwk_client = _FailOnce()  # type: ignore[assignment]

    # When _signing_key_with_retry rebuilds the client, hand back the
    # original stub that resolves to our test public key.
    import app.core.security as sec_mod

    monkeypatch.setattr(sec_mod, "PyJWKClient", lambda *a, **k: saved_client)

    claims = v.verify(mint_token(base_id_claims()))
    assert claims["token_use"] == "id"


def test_jwks_persistent_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from jwt.exceptions import PyJWKClientError

    v = build_verifier()

    class _AlwaysFailClient:
        def get_signing_key_from_jwt(self, _token: str):
            raise PyJWKClientError("unreachable")

    v._jwk_client = _AlwaysFailClient()  # type: ignore[assignment]
    import app.core.security as sec_mod

    monkeypatch.setattr(sec_mod, "PyJWKClient", lambda *a, **k: _AlwaysFailClient())

    with pytest.raises(InvalidTokenError):
        v.verify(mint_token(base_id_claims()))


def test_constructor_rejects_empty_issuer() -> None:
    with pytest.raises(ValueError):
        JwtVerifier(issuer="", audience_ids=["x"])


def test_constructor_rejects_empty_audience_list() -> None:
    with pytest.raises(ValueError):
        JwtVerifier(issuer=DEFAULT_ISSUER, audience_ids=[])


def test_default_jwks_url_is_built_from_issuer() -> None:
    v = JwtVerifier(issuer=DEFAULT_ISSUER, audience_ids=DEFAULT_AUDIENCE_IDS)
    assert v._jwks_url == f"{DEFAULT_ISSUER}/.well-known/jwks.json"
