"""Helpers for building Cognito-shaped JWTs in tests.

A single RSA key is generated at module import time. Tests use
:func:`mint_token` to sign claims with that key and
:func:`build_verifier` to construct a :class:`JwtVerifier` whose
``PyJWKClient`` is monkey-patched to return the matching public key —
no network, fully deterministic.
"""
from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import JwtVerifier

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_PUBLIC_PEM = _PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
TEST_KID = "kid-test-001"

# Defaults matching conftest's _DEFAULT_TEST_CONFIG.
DEFAULT_ISSUER = "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_TESTPOOL00"
DEFAULT_AUDIENCE_IDS = [
    "webclienttest00000000000",
    "iosclienttest00000000000",
    "androidclienttest0000000",
]


def base_id_claims(
    *,
    user_id: str = "01HK3W7QF6VMYG8XR3DQ7B5N6P",
    email: str = "alice@example.com",
    name: str = "Alice",
    aud: str = DEFAULT_AUDIENCE_IDS[0],
    iss: str = DEFAULT_ISSUER,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "cognito-sub-uuid-0001",
        "iss": iss,
        "aud": aud,
        "token_use": "id",
        "auth_time": now,
        "iat": now,
        "exp": now + 3600,
        "email": email,
        "email_verified": True,
        "name": name,
        "custom:user_id": user_id,
    }
    if extra:
        claims.update(extra)
    return claims


def base_access_claims(
    *,
    user_id: str = "01HK3W7QF6VMYG8XR3DQ7B5N6P",
    email: str = "alice@example.com",
    name: str = "Alice",
    client_id: str = DEFAULT_AUDIENCE_IDS[0],
    iss: str = DEFAULT_ISSUER,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "cognito-sub-uuid-0001",
        "iss": iss,
        "client_id": client_id,
        "token_use": "access",
        "auth_time": now,
        "iat": now,
        "exp": now + 3600,
        "scope": "aws.cognito.signin.user.admin",
        # Some Cognito access tokens include these — keep present so
        # Principal.from_claims can read them when used as auth source.
        "email": email,
        "name": name,
        "custom:user_id": user_id,
    }
    if extra:
        claims.update(extra)
    return claims


def mint_token(claims: Mapping[str, Any], *, kid: str = TEST_KID) -> str:
    """Sign ``claims`` with the test RSA key and return the JWT."""
    return jwt.encode(
        dict(claims),
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": kid},
    )


def install_test_jwks(verifier: JwtVerifier) -> None:
    """Replace ``verifier._jwk_client`` with one that resolves to the
    test public key for any token signed with our test private key.
    """
    public_pem = _PUBLIC_PEM

    class _StubJWK:
        def __init__(self) -> None:
            self.key = serialization.load_pem_public_key(public_pem)

    class _StubClient:
        def __init__(self) -> None:
            self.lookup_count = 0

        def get_signing_key_from_jwt(self, _token: str) -> _StubJWK:
            self.lookup_count += 1
            return _StubJWK()

    verifier._jwk_client = _StubClient()  # type: ignore[assignment]


def build_verifier(
    *,
    issuer: str = DEFAULT_ISSUER,
    audience_ids: list[str] | None = None,
) -> JwtVerifier:
    """Construct a :class:`JwtVerifier` with the test JWKs installed."""
    v = JwtVerifier(
        issuer=issuer,
        audience_ids=audience_ids or list(DEFAULT_AUDIENCE_IDS),
        jwks_url="https://example.invalid/.well-known/jwks.json",
    )
    install_test_jwks(v)
    return v


def public_jwks_payload() -> str:
    """Return a JSON JWKs document containing the test public key.

    Used by tests that mock ``urlopen`` for the real ``PyJWKClient``.
    """
    numbers = _PUBLIC_KEY.public_numbers()
    return json.dumps(
        {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": TEST_KID,
                    "use": "sig",
                    "alg": "RS256",
                    "n": _b64u(numbers.n),
                    "e": _b64u(numbers.e),
                }
            ]
        }
    )


def _b64u(value: int) -> str:
    import base64

    byte_len = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(byte_len, "big")).rstrip(b"=").decode()
