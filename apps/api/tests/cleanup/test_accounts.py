"""Tests for the deactivated-account cleanup pass."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.cleanup import accounts as accounts_cleanup
from app.features.me import repository as me_repo
from tests.features.transactions.conftest import (
    auth_headers_for,
    seed_friendship,
    seed_user,
)

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


def _seed_cognito_user(env: dict[str, object], email: str) -> None:
    """Pre-create a Cognito user so admin_disable_user / admin_delete_user
    succeed against moto."""
    cog = env["cognito"]
    cog.admin_create_user(  # type: ignore[attr-defined]
        UserPoolId=str(env["pool_id"]),
        Username=email,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": email.split("@")[0]},
        ],
        MessageAction="SUPPRESS",
    )


def _backdate_deactivation(env: dict[str, object], user_id: str, days: int) -> None:
    long_ago = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0)
    iso = long_ago.isoformat().replace("+00:00", "Z")
    env["users_table"].update_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{user_id}", "SK": "META"},
        UpdateExpression="SET deactivated_at = :ts",
        ExpressionAttributeValues={":ts": iso},
    )


def test_account_cleanup_hard_deletes_old_deactivated_user(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """End-to-end: deactivate via DELETE /v1/me, back-date 31 days,
    run cleanup, verify the user is gone from DDB + Cognito and the
    friendship is gone."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_friendship(txn_env, a_id=A, b_id=B)
    _seed_cognito_user(txn_env, "a@x.com")
    me_repo._set_table_for_tests(txn_env["users_table"])  # type: ignore[arg-type]

    # Deactivate via the route so email_for_cleanup is recorded.
    resp = txn_client.delete("/v1/me", headers=auth_headers_for(A, "a@x.com"))
    assert resp.status_code == 204

    # Back-date the deactivation past the 30-day window.
    _backdate_deactivation(txn_env, A, days=31)

    # Run the cleanup.
    result = accounts_cleanup.cleanup_accounts_once()

    assert result["hard_deleted"] >= 1
    assert result["friendships_deleted"] >= 1
    assert result["cognito_deleted"] >= 1

    # User META row is gone.
    item = txn_env["users_table"].get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"}
    ).get("Item")
    assert item is None

    # Friendship row is gone.
    friendships_b = me_repo.get_friendships(B)
    assert all(r["friend_user_id"] != A for r in friendships_b)


def test_account_cleanup_skips_recent_deactivations(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """A user deactivated yesterday should still be in DDB after the
    cleanup pass (within the 30-day window)."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    _seed_cognito_user(txn_env, "a@x.com")
    me_repo._set_table_for_tests(txn_env["users_table"])  # type: ignore[arg-type]

    txn_client.delete("/v1/me", headers=auth_headers_for(A, "a@x.com"))
    # Don't back-date; deactivated_at is now.

    result = accounts_cleanup.cleanup_accounts_once()
    assert result["hard_deleted"] == 0
    item = txn_env["users_table"].get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"}
    ).get("Item")
    assert item is not None
    assert item.get("status") == "deactivated"


def test_account_cleanup_skips_active_users(
    txn_env: dict[str, object]
) -> None:
    """An ``active`` user older than 30 days is left alone."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    me_repo._set_table_for_tests(txn_env["users_table"])  # type: ignore[arg-type]

    result = accounts_cleanup.cleanup_accounts_once()
    assert result["candidates"] == 0
    assert result["hard_deleted"] == 0


def test_account_cleanup_handles_missing_email_field(
    txn_env: dict[str, object]
) -> None:
    """If the META row was deactivated by an older code path that
    didn't record ``email_for_cleanup``, the user still gets DDB-
    deleted but Cognito delete is skipped (with a warning)."""
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    me_repo._set_table_for_tests(txn_env["users_table"])  # type: ignore[arg-type]
    # Hand-construct a deactivated row WITHOUT email_for_cleanup.
    long_ago = (datetime.now(UTC) - timedelta(days=31)).replace(microsecond=0)
    iso = long_ago.isoformat().replace("+00:00", "Z")
    txn_env["users_table"].update_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{A}", "SK": "META"},
        UpdateExpression=(
            "SET #status = :deact, deactivated_at = :ts, updated_at = :ts"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":deact": "deactivated", ":ts": iso},
    )

    result = accounts_cleanup.cleanup_accounts_once()
    assert result["hard_deleted"] >= 1
    assert result["cognito_deleted"] == 0
