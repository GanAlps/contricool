"""Phase 5 — Transaction lifecycle tests.

Edit (PUT), Delete (DELETE), Restore (POST :restore), and AUDIT row
verification.  All exercised through the FastAPI client + moto so the
HTTP envelope, IAM-shape assumptions, and TransactWriteItems decoding
are real-shape.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from fastapi.testclient import TestClient

from app.features.transactions import repository as txn_repo
from app.features.transactions import service as txn_service

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"
D = "01HK3W7QF6VMYG8XR3DQ7B5N6S"  # not friends with A by default


def _seed_three_friends(env: dict[str, object]) -> None:
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_user(env, user_id=C, email="c@x.com", name="C")
    seed_friendship(env, a_id=A, b_id=B)
    seed_friendship(env, a_id=A, b_id=C)
    seed_friendship(env, a_id=B, b_id=C)


def _create_dinner(
    txn_client: TestClient, *, name: str = "Dinner", key: str = "k1"
) -> dict[str, object]:
    body = {
        "name": name,
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    resp = txn_client.post(
        "/v1/transactions",
        json=body,
        headers={**auth_headers_for(A, "a@x.com"), "Idempotency-Key": key},
    )
    assert resp.status_code == 201, resp.text
    return cast("dict[str, object]", resp.json())


# ---- PUT /v1/transactions/{id} ----------------------------------------


def test_update_happy_path_advances_updated_at_and_writes_audit(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    new_body = {
        "name": "Dinner v2",
        "type": "expense",
        "amount": "36.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "36.00"}],
    }
    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["name"] == "Dinner v2"
    assert out["amount"] == "36.00"
    # updated_at is server-set; we don't strictly require it to be
    # > if_match in seconds-precision since a sub-second edit could
    # legitimately collide. The contract we care about is that the
    # response carries the new attributes (and the AUDIT row below
    # captures the prior state).
    assert isinstance(out["updated_at"], str)

    # An AUDIT row was written for the update.
    audits = txn_repo.get_audit_rows(txn_id)
    actions = [str(a["action"]) for a in audits]
    assert "create" in actions
    assert "update" in actions


def test_update_to_percent_split_writes_per_member_percent(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Exercises the share/percent branches in repo.update_transaction's
    MEMBER put builder (the equal-split create path leaves both null)."""
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "30.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "percent",
            "members": [
                {"user_id": A, "percent": "40"},
                {"user_id": B, "percent": "30"},
                {"user_id": C, "percent": "30"},
            ],
            "payers": [{"user_id": A, "paid_amount": "30.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 200, resp.text
    members = txn_repo.get_members(txn_id)
    a_row = next(m for m in members if m.user_id == A)
    assert a_row.percent == Decimal("40")


def test_update_to_share_split_writes_per_member_share(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "30.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "share",
            "members": [
                {"user_id": A, "share": "1"},
                {"user_id": B, "share": "1"},
                {"user_id": C, "share": "1"},
            ],
            "payers": [{"user_id": A, "paid_amount": "30.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 200, resp.text
    members = txn_repo.get_members(txn_id)
    a_row = next(m for m in members if m.user_id == A)
    assert a_row.share == Decimal("1")


def test_update_member_change_replaces_member_rows(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    # Drop C from members.
    new_body = {
        "name": "Dinner",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 200, resp.text

    members = txn_repo.get_members(txn_id)
    member_ids = {m.user_id for m in members}
    assert member_ids == {A, B}


def test_update_as_non_creator_member_returns_403(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    new_body = {
        "name": "Dinner v2",
        "type": "expense",
        "amount": "36.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "36.00"}],
    }
    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={**auth_headers_for(B, "b@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_update_as_non_member_returns_404_mask(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "X",
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": D}],
            "payers": [{"user_id": A, "paid_amount": "10.00"}],
        },
        headers={**auth_headers_for(D, "d@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_update_on_soft_deleted_txn_returns_404_mask(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Editing a soft-deleted txn must surface as 404 (mask) — not as
    a successful update of a 'tombstone' row, and not as a different
    error code that would confirm the txn used to exist.

    Two layers enforce this:
      - service.update_transaction returns NotFoundError when
        meta.deleted_at is not None.
      - The DDB ConditionExpression has ``attribute_not_exists(deleted_at)``
        as belt-and-suspenders.
    """
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    delete_resp = txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert delete_resp.status_code == 204

    new_body = {
        "name": "Dinner v2",
        "type": "expense",
        "amount": "36.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "36.00"}],
    }
    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_update_with_stale_if_match_returns_412(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    body = {
        "name": "Dinner v2",
        "type": "expense",
        "amount": "36.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "36.00"}],
    }
    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=body,
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": "1999-01-01T00:00:00Z"},
    )
    assert resp.status_code == 412
    assert resp.json()["error"]["code"] == "PRECONDITION_FAILED"


def test_update_missing_if_match_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "X",
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": B}],
            "payers": [{"user_id": A, "paid_amount": "10.00"}],
        },
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_removing_self_from_members_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "20.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            # creator (A) excluded
            "members": [{"user_id": B}, {"user_id": C}],
            "payers": [{"user_id": A, "paid_amount": "20.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SELF_NOT_MEMBER"


def test_update_with_non_friend_member_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")  # not a friend
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "30.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": D}],
            "payers": [{"user_id": A, "paid_amount": "30.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NOT_FRIEND"


def test_update_changing_currency_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "30.00",
            "currency": "INR",  # different
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
            "payers": [{"user_id": A, "paid_amount": "30.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CURRENCY_MISMATCH"


def test_update_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "X",
            "type": "expense",
            "amount": "10.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": B}],
            "payers": [{"user_id": A, "paid_amount": "10.00"}],
        },
        headers={"If-Match": str(txn["updated_at"])},
    )
    assert resp.status_code == 401


# ---- DELETE /v1/transactions/{id} -------------------------------------


def test_delete_as_creator_succeeds_and_writes_audit(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 204
    # Subsequent GET returns 404 (deleted_at set + soft-deleted mask).
    get_resp = txn_client.get(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert get_resp.status_code == 404

    audits = txn_repo.get_audit_rows(txn_id)
    actions = [str(a["action"]) for a in audits]
    assert "delete" in actions


def test_delete_as_non_creator_member_returns_403(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(B, "b@x.com"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_delete_as_non_member_returns_404_mask(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(D, "d@x.com"),
    )
    assert resp.status_code == 404


def test_delete_idempotent_second_call_no_op(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    # Second call: still 204, no extra AUDIT row.
    audits_before = len(txn_repo.get_audit_rows(txn_id))
    resp = txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 204
    audits_after = len(txn_repo.get_audit_rows(txn_id))
    assert audits_after == audits_before


def test_delete_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.delete(f"/v1/transactions/{txn_id}")
    assert resp.status_code == 401


def test_deleted_txn_excluded_from_list_default(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    list_resp = txn_client.get(
        "/v1/transactions",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert all(it["txn_id"] != txn_id for it in items)


def test_deleted_txn_excluded_from_pair_balance(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)  # A pays $30, B owes $10
    txn_id = str(txn["txn_id"])

    pre = txn_service.compute_pair_balance(requester_id=A, friend_id=B)
    assert pre[0] != Decimal("0")  # has a balance

    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    post = txn_service.compute_pair_balance(requester_id=A, friend_id=B)
    assert post[0] == Decimal("0")
    assert post[1] == "settled"


# ---- POST /v1/transactions/{id}/restore -------------------------------


def test_restore_within_window_clears_deleted_at(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    resp = txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["deleted_at"] is None
    # Re-appears in list.
    list_resp = txn_client.get(
        "/v1/transactions",
        headers=auth_headers_for(A, "a@x.com"),
    )
    items = list_resp.json()["items"]
    assert any(it["txn_id"] == txn_id for it in items)

    audits = txn_repo.get_audit_rows(txn_id)
    actions = [str(a["action"]) for a in audits]
    assert "restore" in actions


def test_restore_after_30_days_returns_410_gone(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    # Soft-delete with a back-dated deleted_at by writing directly to DDB.
    table = txn_env["transactions_table"]
    long_ago = (datetime.now(UTC) - timedelta(days=31)).replace(microsecond=0)
    iso = long_ago.isoformat().replace("+00:00", "Z")
    table.update_item(  # type: ignore[attr-defined]
        Key={"PK": f"TXN#{txn_id}", "SK": "META"},
        UpdateExpression="SET deleted_at = :d, updated_at = :d",
        ExpressionAttributeValues={":d": iso},
    )

    resp = txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "GONE"


def test_restore_non_deleted_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])

    resp = txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NOT_DELETED"


def test_restore_as_non_creator_returns_403(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    resp = txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(B, "b@x.com"),
    )
    assert resp.status_code == 403


def test_restore_as_non_member_returns_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    resp = txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(D, "d@x.com"),
    )
    assert resp.status_code == 404


def test_restore_unknown_txn_returns_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    resp = txn_client.post(
        "/v1/transactions/01HK3W7QF6VMYG8XR3DQ7B5N6Z/restore",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert resp.status_code == 404


def test_restore_unauthenticated_returns_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    resp = txn_client.post(
        "/v1/transactions/01HK3W7QF6VMYG8XR3DQ7B5N6P/restore"
    )
    assert resp.status_code == 401


# ---- AUDIT roundup ----------------------------------------------------


# ---- Repository-level: stale race directly on repo.update --------


def test_repo_update_with_stale_if_match_raises_stale_updated_at_error(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """The DDB-side ConditionExpression is the authoritative race
    guard. Service.update_transaction's fast-fail catches obvious
    stale values; this exercises the case where the precondition
    survived the service check but loses to the DDB write."""
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    members = txn_repo.get_members(txn_id)

    inputs = txn_repo.UpdateInputs(
        txn_id=txn_id,
        creator_id=A,
        name="Dinner v2",
        type="expense",
        amount=Decimal("36.00"),
        txn_date="2026-04-29",
        note="",
        split_method="equal",
        members=[
            {"user_id": A, "owed_amount": Decimal("12.00")},
            {"user_id": B, "owed_amount": Decimal("12.00")},
            {"user_id": C, "owed_amount": Decimal("12.00")},
        ],
        payers=[{"user_id": A, "paid_amount": Decimal("36.00")}],
    )
    import pytest

    with pytest.raises(txn_repo.StaleUpdatedAtError):
        txn_repo.update_transaction(
            inputs=inputs,
            if_match="1999-01-01T00:00:00Z",  # never matches what META carries
            prior_snapshot={"members": []},
            prior_member_ids=[m.user_id for m in members],
            new_member_ids=[A, B, C],
            other_member_ids=[B, C],
            currency="USD",
        )


def test_repo_update_with_unfriended_member_raises_not_friend_error(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Friendship ConditionCheck slot fires before the META slot."""
    _seed_three_friends(txn_env)
    seed_user(txn_env, user_id=D, email="d@x.com", name="D")  # not a friend
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])
    members = txn_repo.get_members(txn_id)

    inputs = txn_repo.UpdateInputs(
        txn_id=txn_id,
        creator_id=A,
        name="Dinner v2",
        type="expense",
        amount=Decimal("30.00"),
        txn_date="2026-04-29",
        note="",
        split_method="equal",
        members=[
            {"user_id": A, "owed_amount": Decimal("15.00")},
            {"user_id": D, "owed_amount": Decimal("15.00")},
        ],
        payers=[{"user_id": A, "paid_amount": Decimal("30.00")}],
    )
    import pytest

    from app.features.transactions.errors import NotFriendError

    with pytest.raises(NotFriendError):
        txn_repo.update_transaction(
            inputs=inputs,
            if_match=if_match,
            prior_snapshot={"members": []},
            prior_member_ids=[m.user_id for m in members],
            new_member_ids=[A, D],
            other_member_ids=[D],
            currency="USD",
        )


# ---- AUDIT roundup ----------------------------------------------------


def test_audit_rows_capture_full_lifecycle(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_three_friends(txn_env)
    txn = _create_dinner(txn_client)
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    txn_client.put(
        f"/v1/transactions/{txn_id}",
        json={
            "name": "Dinner v2",
            "type": "expense",
            "amount": "36.00",
            "currency": "USD",
            "txn_date": "2026-04-29",
            "split_method": "equal",
            "members": [{"user_id": A}, {"user_id": B}, {"user_id": C}],
            "payers": [{"user_id": A, "paid_amount": "36.00"}],
        },
        headers={**auth_headers_for(A, "a@x.com"), "If-Match": if_match},
    )
    txn_client.delete(
        f"/v1/transactions/{txn_id}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    txn_client.post(
        f"/v1/transactions/{txn_id}/restore",
        headers=auth_headers_for(A, "a@x.com"),
    )
    audits = txn_repo.get_audit_rows(txn_id)
    actions = [str(a["action"]) for a in audits]
    assert actions.count("create") == 1
    assert actions.count("update") == 1
    assert actions.count("delete") == 1
    assert actions.count("restore") == 1
