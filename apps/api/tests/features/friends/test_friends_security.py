"""Auth + log-redaction security tests for the friends feature."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from tests._jwt_helpers import (
    base_id_claims,
    build_verifier,
    mint_token,
)

from .conftest import seed_user

REQUESTER_ID = "01HK3W7QF6VMYG8XR3DQ7B5N6P"


@pytest.fixture
def authed_headers() -> Iterator[dict[str, str]]:
    deps.set_verifier_for_tests(build_verifier())
    token = mint_token(
        base_id_claims(user_id=REQUESTER_ID, email="r@example.com", name="R")
    )
    try:
        yield {"Authorization": f"Bearer {token}"}
    finally:
        deps.set_verifier_for_tests(None)


def test_n7_unauthenticated_all_routes(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    """N7: every /v1/friends/* route requires a bearer."""
    target = "01HZZZZZZZZZZZZZZZZZZZZZZZ"
    cases = [
        ("POST", "/v1/friends/add", {"email": "x@example.com"}),
        ("GET", "/v1/friends", None),
        ("DELETE", f"/v1/friends/{target}", None),
        ("GET", f"/v1/friends/{target}/balance", None),
    ]
    for method, path, body in cases:
        if method == "POST":
            r = friends_client.post(path, json=body)
        elif method == "GET":
            r = friends_client.get(path)
        else:
            r = friends_client.delete(path)
        assert r.status_code == 401, f"{method} {path}"


def test_n8_tampered_jwt_rejected(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    """N8: any JWT not signed by our verifier's key → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        r = friends_client.get(
            "/v1/friends",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        assert r.status_code == 401
    finally:
        deps.set_verifier_for_tests(None)


def test_n8_wrong_pool_jwt_rejected(
    friends_client: TestClient, friends_env: dict[str, object]
) -> None:
    """N8 (cont): JWT from a different Cognito pool → 401."""
    deps.set_verifier_for_tests(build_verifier())
    try:
        token = mint_token(
            base_id_claims(
                user_id=REQUESTER_ID,
                email="r@example.com",
                name="R",
                iss="https://cognito-idp.us-west-2.amazonaws.com/us-west-2_OTHER",
            )
        )
        r = friends_client.get(
            "/v1/friends", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
    finally:
        deps.set_verifier_for_tests(None)


def test_n10_no_raw_email_in_logs_on_add(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """N10: add-friend log line does not contain the raw email."""
    seed_user(
        friends_env,
        user_id=REQUESTER_ID,
        email="requester@example.com",
        name="R",
    )
    seed_user(
        friends_env,
        user_id="01HKTARGET0000000000000000",
        email="target@example.com",
        name="T",
    )
    with caplog.at_level("INFO"):
        friends_client.post(
            "/v1/friends/add",
            json={"email": "target@example.com"},
            headers=authed_headers,
        )
    for record in caplog.records:
        assert "target@example.com" not in str(record.message)
        assert "target@example.com" not in str(getattr(record, "args", ""))


def test_n10_no_raw_email_in_logs_on_user_not_found(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same redaction invariant on the failed-lookup path."""
    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    with caplog.at_level("INFO"):
        friends_client.post(
            "/v1/friends/add",
            json={"email": "ghost@example.com"},
            headers=authed_headers,
        )
    for record in caplog.records:
        assert "ghost@example.com" not in str(record.message)


def test_friend_added_log_carries_email_hash(
    friends_client: TestClient,
    friends_env: dict[str, object],
    authed_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NFR4.2: the friend_added log line carries an email_hash field
    so on-call can correlate without ever seeing the raw address."""
    from app.core.lookup_hash import email_hash

    seed_user(
        friends_env, user_id=REQUESTER_ID, email="r@example.com", name="R"
    )
    seed_user(
        friends_env,
        user_id="01HKTARGET0000000000000000",
        email="target@example.com",
        name="T",
    )
    with caplog.at_level("INFO"):
        r = friends_client.post(
            "/v1/friends/add",
            json={"email": "target@example.com"},
            headers=authed_headers,
        )
    assert r.status_code == 200
    expected = email_hash("target@example.com")
    matching = [
        rec
        for rec in caplog.records
        if "friend_added" in str(rec.message)
        and getattr(rec, "email_hash", None) == expected
    ]
    assert matching, "friend_added log line missing email_hash field"
