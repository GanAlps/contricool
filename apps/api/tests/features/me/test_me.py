"""``DELETE /v1/me`` + ``GET /v1/me/export`` integration tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.features.me import repository as me_repo
from tests.features.transactions.conftest import (
    auth_headers_for,
    seed_friendship,
    seed_user,
)

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


def _seed_two_friends_with_txn(env: dict[str, object], txn_client: TestClient) -> str:
    """Common setup: A and B friends, A creates a $20 dinner with B.
    Returns the dinner txn_id."""
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_friendship(env, a_id=A, b_id=B)
    body = {
        "name": "Dinner",
        "type": "expense",
        "amount": "20.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "20.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A, "a@x.com"), "Idempotency-Key": "k1"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["txn_id"])


# ---- DELETE /v1/me ---------------------------------------------------


def test_delete_me_marks_user_deactivated(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    # Pre-create a Cognito user so admin_disable_user / sign-out succeed.
    cog = txn_env["cognito"]
    cog.admin_create_user(  # type: ignore[attr-defined]
        UserPoolId=str(txn_env["pool_id"]),
        Username="a@x.com",
        UserAttributes=[
            {"Name": "email", "Value": "a@x.com"},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": "A"},
        ],
        MessageAction="SUPPRESS",
    )

    resp = txn_client.delete(
        "/v1/me", headers=auth_headers_for(A, "a@x.com")
    )
    assert resp.status_code == 204

    # META row carries status=deactivated.
    item = txn_env["users_table"].get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"}
    ).get("Item")
    assert item is not None
    assert item.get("status") == "deactivated"
    assert "deactivated_at" in item


def test_delete_me_idempotent(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    cog = txn_env["cognito"]
    cog.admin_create_user(  # type: ignore[attr-defined]
        UserPoolId=str(txn_env["pool_id"]),
        Username="a@x.com",
        UserAttributes=[
            {"Name": "email", "Value": "a@x.com"},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": "A"},
        ],
        MessageAction="SUPPRESS",
    )
    h = auth_headers_for(A, "a@x.com")
    r1 = txn_client.delete("/v1/me", headers=h)
    assert r1.status_code == 204
    r2 = txn_client.delete("/v1/me", headers=h)
    assert r2.status_code == 204


def test_delete_me_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    resp = txn_client.delete("/v1/me")
    assert resp.status_code == 401


# ---- GET /v1/me/export -----------------------------------------------


def test_export_returns_full_self_data(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    txn_id = _seed_two_friends_with_txn(txn_env, txn_client)
    resp = txn_client.get(
        "/v1/me/export", headers=auth_headers_for(A, "a@x.com")
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["profile"]["user_id"] == A
    assert out["profile"]["name"] == "A"
    assert out["profile"]["currency"] == "USD"
    # B is in the friendships list.
    assert any(f["friend_user_id"] == B for f in out["friendships"])
    # Dinner transaction included.
    assert any(t["txn_id"] == txn_id for t in out["transactions"])
    txn = next(t for t in out["transactions"] if t["txn_id"] == txn_id)
    assert txn["amount"] == "20.00"
    assert any(m["user_id"] == A for m in txn["members"])
    assert any(m["user_id"] == B for m in txn["members"])
    assert "exported_at" in out


def test_export_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    resp = txn_client.get("/v1/me/export")
    assert resp.status_code == 401


def test_export_unknown_user_returns_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Edge case: token claims a user_id that has no META row.
    Service raises NOT_FOUND so the requester can't conjure data
    via a hand-rolled JWT — and the existence check runs *before*
    the rate-limit consume, so this 404 doesn't burn a quota slot.
    """
    resp = txn_client.get(
        "/v1/me/export", headers=auth_headers_for(A, "a@x.com")
    )
    assert resp.status_code == 404
    # Rate-limit row was not written.
    rate_row = txn_env["users_table"].get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "EXPORT_RATE"}
    ).get("Item")
    assert rate_row is None


def test_export_rate_limited_after_one(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Second export within the cooldown window is 429."""
    _seed_two_friends_with_txn(txn_env, txn_client)
    h = auth_headers_for(A, "a@x.com")
    r1 = txn_client.get("/v1/me/export", headers=h)
    assert r1.status_code == 200
    r2 = txn_client.get("/v1/me/export", headers=h)
    assert r2.status_code == 429
    assert r2.json()["error"]["code"] == "RATE_LIMITED"


def test_export_succeeds_after_cooldown(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Bypass-time fast-forward: write a stale ``last_at`` and
    confirm a new export succeeds."""
    _seed_two_friends_with_txn(txn_env, txn_client)
    h = auth_headers_for(A, "a@x.com")
    r1 = txn_client.get("/v1/me/export", headers=h)
    assert r1.status_code == 200
    # Backdate the rate-limit row.
    long_ago = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    txn_env["users_table"].update_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "EXPORT_RATE"},
        UpdateExpression="SET last_at = :ts",
        ExpressionAttributeValues={
            ":ts": long_ago.isoformat().replace("+00:00", "Z")
        },
    )
    r2 = txn_client.get("/v1/me/export", headers=h)
    assert r2.status_code == 200


# ---- repository edges ------------------------------------------------


def test_get_friendships_returns_both_sides(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Friendship rows store the canonical pair on one side and the
    GSI1 pivot on the other. The export must surface both."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_friendship(txn_env, a_id=A, b_id=B)
    rows = me_repo.get_friendships(A)
    assert any(r["friend_user_id"] == B for r in rows)
    rows_b = me_repo.get_friendships(B)
    assert any(r["friend_user_id"] == A for r in rows_b)
