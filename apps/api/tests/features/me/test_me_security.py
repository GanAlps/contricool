"""Negative auth tests for `/v1/me` — RED LINE 3 coverage.

Both ``DELETE /v1/me`` and ``GET /v1/me/export`` are gated by the
``current_principal`` dependency, so they share the rejection paths
exercised below.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core import dependencies as deps
from tests._jwt_helpers import base_id_claims, build_verifier, mint_token

USER_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6P"


def _routes(client: TestClient) -> list[tuple[str, object]]:
    return [
        ("DELETE /v1/me", lambda h=None: client.delete("/v1/me", headers=h or {})),
        (
            "GET /v1/me/export",
            lambda h=None: client.get("/v1/me/export", headers=h or {}),
        ),
    ]


def test_missing_jwt_rejected(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """No Authorization header → 401 on both routes."""
    for label, call in _routes(txn_client):
        resp = call()
        assert resp.status_code == 401, label


def test_tampered_jwt_rejected(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Garbage bearer token → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        headers = {"Authorization": "Bearer not-a-jwt"}
        for label, call in _routes(txn_client):
            resp = call(headers)
            assert resp.status_code == 401, label
    finally:
        deps.set_verifier_for_tests(None)


def test_wrong_pool_jwt_rejected(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """JWT minted by a different Cognito pool issuer → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        token = mint_token(
            base_id_claims(
                user_id=USER_ID,
                email="a@x.com",
                name="A",
                iss="https://cognito-idp.us-west-2.amazonaws.com/us-west-2_OTHER",
            )
        )
        headers = {"Authorization": f"Bearer {token}"}
        for label, call in _routes(txn_client):
            resp = call(headers)
            assert resp.status_code == 401, label
    finally:
        deps.set_verifier_for_tests(None)


def test_expired_jwt_rejected(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """JWT with an exp in the past → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        now = int(time.time())
        claims = base_id_claims(user_id=USER_ID, email="a@x.com", name="A")
        # Mint with iat / exp safely in the past so PyJWT rejects on `exp`.
        claims["iat"] = now - 7200
        claims["exp"] = now - 3600
        token = mint_token(claims)
        headers = {"Authorization": f"Bearer {token}"}
        for label, call in _routes(txn_client):
            resp = call(headers)
            assert resp.status_code == 401, label
    finally:
        deps.set_verifier_for_tests(None)
