"""Unit tests for ``service.validate_create_payload`` — hit every
typed-error branch without going through HTTP."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.features.transactions.errors import (
    MemberCountError,
    OwedSumError,
    PaidSumError,
    PayerNotMemberError,
    PercentSumError,
    SelfNotMemberError,
    ValidationFailedError,
)
from app.features.transactions.models import (
    CreateTransactionRequest,
    MemberInput,
    PayerInput,
)
from app.features.transactions.service import validate_create_payload

A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"
C = "01HK3W7QF6VMYG8XR3DQ7B5N6R"


def _eq(**kw: object) -> CreateTransactionRequest:
    """Equal-split, 3 members, A creator/payer factory."""
    members = kw.get(
        "members", [MemberInput(user_id=A), MemberInput(user_id=B), MemberInput(user_id=C)]
    )
    payers = kw.get("payers", [PayerInput(user_id=A, paid_amount=Decimal("30.00"))])
    return CreateTransactionRequest(
        name=str(kw.get("name", "Dinner")),
        type=kw.get("type", "expense"),  # type: ignore[arg-type]
        amount=Decimal(str(kw.get("amount", "30.00"))),
        currency=kw.get("currency", "USD"),  # type: ignore[arg-type]
        txn_date=kw.get("txn_date", "2026-04-29"),  # type: ignore[arg-type]
        split_method=kw.get("split_method", "equal"),  # type: ignore[arg-type]
        members=members,  # type: ignore[arg-type]
        payers=payers,  # type: ignore[arg-type]
    )


def test_validate_min_members() -> None:
    body = _eq(
        members=[MemberInput(user_id=A)],
        payers=[PayerInput(user_id=A, paid_amount=Decimal("30.00"))],
    )
    with pytest.raises(MemberCountError) as exc:
        validate_create_payload(requester_id=A, body=body)
    assert exc.value.code == "MIN_MEMBERS"


# NB: ``MAX_MEMBERS`` is enforced upstream by Pydantic
# (``CreateTransactionRequest.members`` carries ``max_length=10``), so
# the service-layer check is defensive and not exercisable via the
# parsed-body path. The service-side branch is marked ``# pragma: no
# cover`` in service.py.


def test_validate_duplicate_member_ids() -> None:
    body = _eq(
        members=[MemberInput(user_id=A), MemberInput(user_id=A), MemberInput(user_id=B)]
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_self_not_member() -> None:
    body = _eq(
        members=[MemberInput(user_id=B), MemberInput(user_id=C)],
        amount="20.00",
        payers=[PayerInput(user_id=B, paid_amount=Decimal("20.00"))],
    )
    with pytest.raises(SelfNotMemberError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_duplicate_payer_ids() -> None:
    body = _eq(
        payers=[
            PayerInput(user_id=A, paid_amount=Decimal("15.00")),
            PayerInput(user_id=A, paid_amount=Decimal("15.00")),
        ],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_payer_not_member() -> None:
    other = "01HK3W7QF6VMYG8XR3DQ7B5N6S"
    body = _eq(payers=[PayerInput(user_id=other, paid_amount=Decimal("30.00"))])
    with pytest.raises(PayerNotMemberError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_paid_sum_mismatch() -> None:
    body = _eq(
        amount="30.00",
        payers=[PayerInput(user_id=A, paid_amount=Decimal("20.00"))],
    )
    with pytest.raises(PaidSumError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_amount_method_missing_owed() -> None:
    body = _eq(
        split_method="amount",
        members=[
            MemberInput(user_id=A, owed_amount=Decimal("10.00")),
            MemberInput(user_id=B),  # missing
            MemberInput(user_id=C, owed_amount=Decimal("10.00")),
        ],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_amount_method_owed_sum_mismatch() -> None:
    body = _eq(
        split_method="amount",
        members=[
            MemberInput(user_id=A, owed_amount=Decimal("5.00")),
            MemberInput(user_id=B, owed_amount=Decimal("5.00")),
            MemberInput(user_id=C, owed_amount=Decimal("5.00")),
        ],
    )
    with pytest.raises(OwedSumError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_share_method_missing_share() -> None:
    body = _eq(
        split_method="share",
        members=[
            MemberInput(user_id=A, share=Decimal("1")),
            MemberInput(user_id=B),  # no share
            MemberInput(user_id=C, share=Decimal("1")),
        ],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_percent_method_missing_percent() -> None:
    body = _eq(
        split_method="percent",
        members=[
            MemberInput(user_id=A, percent=Decimal("33.33")),
            MemberInput(user_id=B),  # missing
            MemberInput(user_id=C, percent=Decimal("33.34")),
        ],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_percent_sum_off() -> None:
    body = _eq(
        split_method="percent",
        members=[
            MemberInput(user_id=A, percent=Decimal("30")),
            MemberInput(user_id=B, percent=Decimal("30")),
            MemberInput(user_id=C, percent=Decimal("30")),
        ],
    )
    with pytest.raises(PercentSumError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_settlement_wrong_member_count() -> None:
    body = _eq(
        type="settlement",
        split_method="amount",
        members=[
            MemberInput(user_id=A, owed_amount=Decimal("10.00")),
            MemberInput(user_id=B, owed_amount=Decimal("10.00")),
            MemberInput(user_id=C, owed_amount=Decimal("10.00")),
        ],
    )
    with pytest.raises(MemberCountError) as exc:
        validate_create_payload(requester_id=A, body=body)
    assert exc.value.code == "SETTLEMENT_SHAPE"


def test_validate_settlement_two_payers_rejected() -> None:
    body = _eq(
        type="settlement",
        amount="10.00",
        split_method="amount",
        members=[
            MemberInput(user_id=A, owed_amount=Decimal("0.00")),
            MemberInput(user_id=B, owed_amount=Decimal("10.00")),
        ],
        payers=[
            PayerInput(user_id=A, paid_amount=Decimal("5.00")),
            PayerInput(user_id=B, paid_amount=Decimal("5.00")),
        ],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_settlement_wrong_split_method() -> None:
    body = _eq(
        type="settlement",
        amount="10.00",
        split_method="equal",
        members=[
            MemberInput(user_id=A),
            MemberInput(user_id=B),
        ],
        payers=[PayerInput(user_id=A, paid_amount=Decimal("10.00"))],
    )
    with pytest.raises(ValidationFailedError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_settlement_wrong_owed_amounts() -> None:
    body = _eq(
        type="settlement",
        amount="10.00",
        split_method="amount",
        members=[
            MemberInput(user_id=A, owed_amount=Decimal("5.00")),  # should be 0
            MemberInput(user_id=B, owed_amount=Decimal("5.00")),  # should be 10
        ],
        payers=[PayerInput(user_id=A, paid_amount=Decimal("10.00"))],
    )
    with pytest.raises(OwedSumError):
        validate_create_payload(requester_id=A, body=body)


def test_validate_happy_path_returns_none() -> None:
    body = _eq()
    assert validate_create_payload(requester_id=A, body=body) is None
