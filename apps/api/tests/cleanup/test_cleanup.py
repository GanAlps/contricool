"""Tests for the daily cleanup Lambda.

Exercises the three repo helpers it composes (``scan_soft_deleted``,
``hard_delete_transaction``, ``set_audit_ttl_for_purge``) plus the
handler entrypoint.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.cleanup.main import cleanup_once, handler
from app.features.transactions import repository as txn_repo
from tests.features.transactions.conftest import (
    auth_headers_for,
    seed_friendship,
    seed_user,
)

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


def _create_dinner(txn_client: TestClient) -> str:
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


def _backdate_deletion(env: dict[str, object], txn_id: str, days_ago: int) -> None:
    table = env["transactions_table"]
    long_ago = (datetime.now(UTC) - timedelta(days=days_ago)).replace(microsecond=0)
    iso = long_ago.isoformat().replace("+00:00", "Z")
    table.update_item(  # type: ignore[attr-defined]
        Key={"PK": f"TXN#{txn_id}", "SK": "META"},
        UpdateExpression="SET deleted_at = :d, updated_at = :d",
        ExpressionAttributeValues={":d": iso},
    )


def test_cleanup_hard_deletes_old_soft_deleted_txn(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_friendship(txn_env, a_id=A, b_id=B)
    txn_id = _create_dinner(txn_client)
    # Soft-delete + back-date past the 30-day window.
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    _backdate_deletion(txn_env, txn_id, days_ago=31)

    result = cleanup_once()
    assert result["candidates"] >= 1
    assert result["hard_deleted"] >= 1

    # META + MEMBER rows are gone.
    assert txn_repo.get_meta(txn_id) is None
    assert txn_repo.get_members(txn_id) == []

    # AUDIT rows still exist but carry a ttl attribute now.
    audits = txn_repo.get_audit_rows(txn_id)
    assert len(audits) >= 1
    for row in audits:
        assert "ttl" in row
        assert int(row["ttl"]) > int(datetime.now(UTC).timestamp())


def test_cleanup_skips_recently_deleted_txn(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_friendship(txn_env, a_id=A, b_id=B)
    txn_id = _create_dinner(txn_client)
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    # NOT back-dated — still within the window.

    result = cleanup_once()
    assert result["hard_deleted"] == 0
    # META still present.
    assert txn_repo.get_meta(txn_id) is not None


def test_cleanup_skips_active_txn(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_friendship(txn_env, a_id=A, b_id=B)
    _create_dinner(txn_client)
    # Never deleted.

    result = cleanup_once()
    assert result["candidates"] == 0
    assert result["hard_deleted"] == 0


def test_cleanup_with_no_audit_rows_returns_zero_marked(
    txn_env: dict[str, object],
) -> None:
    """``set_audit_ttl_for_purge`` should be a no-op for a txn with no
    audit rows (defensive — shouldn't happen in normal flow but the
    helper is also a public utility)."""
    n = txn_repo.set_audit_ttl_for_purge(
        "01HK3W7QF6VMYG8XR3DQ7B5N7Z", ttl_seconds_from_now=86400
    )
    assert n == 0


def test_cleanup_handler_entrypoint_returns_summary(
    txn_env: dict[str, object],
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    out = handler({}, None)
    assert "candidates" in out
    assert "hard_deleted" in out
    assert "audit_rows_marked" in out
    assert out["hard_deleted"] == 0
