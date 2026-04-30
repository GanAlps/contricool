"""Tests for transaction comments — POST/GET endpoints + system
comments emitted on edit."""
from __future__ import annotations

from decimal import Decimal
from typing import cast

from fastapi.testclient import TestClient

from app.features.transactions import comments as txn_comments

from .conftest import auth_headers_for, seed_friendship, seed_user

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"
OUTSIDER = "01HK3W7QF6VMYG8XR3DQ7B5N6T"


def _seed_two_friends(env: dict[str, object]) -> None:
    seed_user(env, user_id=A, email="a@x.com", name="A")
    seed_user(env, user_id=B, email="b@x.com", name="B")
    seed_friendship(env, a_id=A, b_id=B)


def _create_txn(
    client: TestClient,
    *,
    members: list[str],
    payer: str,
    payer_email: str,
    amount: str = "20.00",
    name: str = "Dinner",
    key: str = "ckey-1",
) -> dict[str, object]:
    body = {
        "name": name,
        "type": "expense",
        "amount": amount,
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": m} for m in members],
        "payers": [{"user_id": payer, "paid_amount": amount}],
    }
    resp = client.post(
        "/v1/transactions",
        json=body,
        headers={
            **auth_headers_for(payer, payer_email),
            "Idempotency-Key": key,
        },
    )
    assert resp.status_code == 201, resp.text
    return cast("dict[str, object]", resp.json())


# ---- POST /v1/transactions/{id}/comments ---------------------------


def test_member_can_post_comment(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com"
    )
    txn_id = str(txn["txn_id"])
    r = txn_client.post(
        f"/v1/transactions/{txn_id}/comments",
        json={"body": "  Great dinner!  "},
        headers=auth_headers_for(B, "b@x.com"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["txn_id"] == txn_id
    assert body["author_id"] == B
    assert body["kind"] == "user"
    assert body["body"] == "Great dinner!"
    assert "comment_id" in body
    assert "created_at" in body


def test_post_comment_blank_body_after_trim_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="blankkey",
    )
    r = txn_client.post(
        f"/v1/transactions/{txn['txn_id']}/comments",
        json={"body": "   "},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_post_comment_empty_body_pydantic_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="emptykey",
    )
    r = txn_client.post(
        f"/v1/transactions/{txn['txn_id']}/comments",
        json={"body": ""},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_post_comment_too_long_returns_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="longkey",
    )
    r = txn_client.post(
        f"/v1/transactions/{txn['txn_id']}/comments",
        json={"body": "x" * 1001},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_non_member_cannot_post_comment(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Mask: outsiders see 404 — never confirm txn existence."""
    _seed_two_friends(txn_env)
    seed_user(txn_env, user_id=OUTSIDER, email="out@x.com", name="Out")
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="outkey",
    )
    r = txn_client.post(
        f"/v1/transactions/{txn['txn_id']}/comments",
        json={"body": "hi"},
        headers=auth_headers_for(OUTSIDER, "out@x.com"),
    )
    assert r.status_code == 404


def test_post_comment_unauthenticated_401(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    r = txn_client.post(
        "/v1/transactions/01HK3W7QF6VMYG8XR3DQ7B5N6P/comments",
        json={"body": "x"},
    )
    assert r.status_code == 401


def test_post_comment_malformed_txn_id_422(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    r = txn_client.post(
        "/v1/transactions/not-a-ulid/comments",
        json={"body": "hi"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 422


def test_post_comment_unknown_txn_id_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    r = txn_client.post(
        "/v1/transactions/01HK3W7QF6VMYG8XR3DQ7B5N6Z/comments",
        json={"body": "hi"},
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 404


def test_list_comments_unknown_txn_id_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    r = txn_client.get(
        "/v1/transactions/01HK3W7QF6VMYG8XR3DQ7B5N6Z/comments",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 404


# ---- build_edit_summary unit tests ---------------------------------


def test_build_edit_summary_skips_keys_absent_on_both_sides() -> None:
    """When a key is missing from both prior + new, the diff helper
    should *not* synthesise a "None → None" line."""
    summary = txn_comments.build_edit_summary(
        prior_snapshot={"name": "X", "amount": "1.00"},
        new_inputs={"name": "Y", "amount": "1.00"},
    )
    assert summary is not None
    assert "name" in summary
    # No "type", "currency", "txn_date", "note", "split_method" lines.
    assert "type" not in summary
    assert "currency" not in summary


def test_build_edit_summary_decimal_str_no_scientific() -> None:
    """Decimals print as plain numbers, not scientific notation."""
    summary = txn_comments.build_edit_summary(
        prior_snapshot={"amount": Decimal("100")},
        new_inputs={"amount": Decimal("200")},
    )
    assert summary is not None
    assert "100" in summary and "200" in summary
    assert "E+" not in summary


def test_build_edit_summary_returns_none_when_unchanged() -> None:
    assert (
        txn_comments.build_edit_summary(
            prior_snapshot={"name": "X"},
            new_inputs={"name": "X"},
        )
        is None
    )


# ---- GET /v1/transactions/{id}/comments ----------------------------


def test_list_comments_oldest_first(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="lst1",
    )
    for n in range(3):
        r = txn_client.post(
            f"/v1/transactions/{txn['txn_id']}/comments",
            json={"body": f"#{n}"},
            headers=auth_headers_for(A, "a@x.com"),
        )
        assert r.status_code == 201, r.text
    r = txn_client.get(
        f"/v1/transactions/{txn['txn_id']}/comments",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200
    body = r.json()
    bodies = [it["body"] for it in body["items"]]
    assert bodies == ["#0", "#1", "#2"]


def test_list_comments_non_member_404(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    seed_user(txn_env, user_id=OUTSIDER, email="out@x.com", name="Out")
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="lst2",
    )
    r = txn_client.get(
        f"/v1/transactions/{txn['txn_id']}/comments",
        headers=auth_headers_for(OUTSIDER, "out@x.com"),
    )
    assert r.status_code == 404


def test_list_comments_pagination(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Walk every page so the cursor inclusivity bug
    (regression: query_comments BETWEEN drops the trailing row when
    Limit doesn't account for the filtered cursor) stays fixed."""
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client, members=[A, B], payer=A, payer_email="a@x.com",
        key="page1",
    )
    for n in range(5):
        r = txn_client.post(
            f"/v1/transactions/{txn['txn_id']}/comments",
            json={"body": f"#{n}"},
            headers=auth_headers_for(A, "a@x.com"),
        )
        assert r.status_code == 201
    r = txn_client.get(
        f"/v1/transactions/{txn['txn_id']}/comments?limit=2",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200
    body = r.json()
    assert [it["body"] for it in body["items"]] == ["#0", "#1"]
    assert body["next_cursor"] is not None

    r2 = txn_client.get(
        f"/v1/transactions/{txn['txn_id']}/comments?limit=2&cursor={body['next_cursor']}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert [it["body"] for it in body2["items"]] == ["#2", "#3"]
    # 5 comments, page size 2 → there is still #4 to return.
    assert body2["next_cursor"] is not None

    r3 = txn_client.get(
        f"/v1/transactions/{txn['txn_id']}/comments?limit=2&cursor={body2['next_cursor']}",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r3.status_code == 200
    body3 = r3.json()
    assert [it["body"] for it in body3["items"]] == ["#4"]
    assert body3["next_cursor"] is None


# ---- System comment on update --------------------------------------


def test_edit_emits_system_comment_with_diff_summary(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client,
        members=[A, B],
        payer=A,
        payer_email="a@x.com",
        amount="20.00",
        key="edit1",
    )
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    new_body = {
        "name": "Lunch",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    r = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={
            **auth_headers_for(A, "a@x.com"),
            "If-Match": if_match,
        },
    )
    assert r.status_code == 200, r.text

    r = txn_client.get(
        f"/v1/transactions/{txn_id}/comments",
        headers=auth_headers_for(A, "a@x.com"),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    sys_items = [it for it in items if it["kind"] == "system"]
    assert len(sys_items) == 1
    sys_body = sys_items[0]["body"]
    assert "Updated transaction" in sys_body
    assert "name" in sys_body
    assert "Dinner" in sys_body and "Lunch" in sys_body
    assert "amount" in sys_body
    assert "20.00" in sys_body and "30.00" in sys_body
    assert sys_items[0]["author_id"] == "system"


def test_edit_system_comment_suppressed_when_noop(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    """Re-PUT the same body — no diff → no system comment emitted."""
    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client,
        members=[A, B],
        payer=A,
        payer_email="a@x.com",
        key="noop1",
    )
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])
    same_body = {
        "name": "Dinner",
        "type": "expense",
        "amount": "20.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "20.00"}],
    }
    r = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=same_body,
        headers={
            **auth_headers_for(A, "a@x.com"),
            "If-Match": if_match,
        },
    )
    assert r.status_code == 200, r.text

    r = txn_client.get(
        f"/v1/transactions/{txn_id}/comments",
        headers=auth_headers_for(A, "a@x.com"),
    )
    items = r.json()["items"]
    assert all(it["kind"] != "system" for it in items)


def test_edit_system_comment_summarises_member_changes(
    txn_env: dict[str, object], txn_client: TestClient
) -> None:
    seed_user(txn_env, user_id=A, email="a@x.com", name="A")
    seed_user(txn_env, user_id=B, email="b@x.com", name="B")
    seed_user(txn_env, user_id=C, email="c@x.com", name="C")
    seed_friendship(txn_env, a_id=A, b_id=B)
    seed_friendship(txn_env, a_id=A, b_id=C)

    txn = _create_txn(
        txn_client,
        members=[A, B],
        payer=A,
        payer_email="a@x.com",
        amount="20.00",
        key="memchange",
    )
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    new_body = {
        "name": "Dinner",
        "type": "expense",
        "amount": "20.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": C}],
        "payers": [{"user_id": A, "paid_amount": "20.00"}],
    }
    r = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={
            **auth_headers_for(A, "a@x.com"),
            "If-Match": if_match,
        },
    )
    assert r.status_code == 200, r.text

    r = txn_client.get(
        f"/v1/transactions/{txn_id}/comments",
        headers=auth_headers_for(A, "a@x.com"),
    )
    sys = next(it for it in r.json()["items"] if it["kind"] == "system")
    assert "members" in sys["body"]
    assert C in sys["body"]
    assert B in sys["body"]


# ---- Repository edge: best-effort system-comment failure -----------


def test_system_comment_failure_does_not_break_update(
    txn_env: dict[str, object], txn_client: TestClient, monkeypatch
) -> None:
    """Simulate a DDB write failure on the SYSTEM comment row; the
    update should still return 200 — comments are best-effort."""
    from app.features.transactions import repository as txn_repo

    _seed_two_friends(txn_env)
    txn = _create_txn(
        txn_client,
        members=[A, B],
        payer=A,
        payer_email="a@x.com",
        amount="20.00",
        key="failkey",
    )
    txn_id = str(txn["txn_id"])
    if_match = str(txn["updated_at"])

    def _boom(**kwargs: object) -> object:
        raise RuntimeError("synthetic put_comment failure")

    monkeypatch.setattr(txn_repo, "put_comment", _boom)

    new_body = {
        "name": "Lunch",
        "type": "expense",
        "amount": "30.00",
        "currency": "USD",
        "txn_date": "2026-04-29",
        "split_method": "equal",
        "members": [{"user_id": A}, {"user_id": B}],
        "payers": [{"user_id": A, "paid_amount": "30.00"}],
    }
    r = txn_client.put(
        f"/v1/transactions/{txn_id}",
        json=new_body,
        headers={
            **auth_headers_for(A, "a@x.com"),
            "If-Match": if_match,
        },
    )
    assert r.status_code == 200, r.text
