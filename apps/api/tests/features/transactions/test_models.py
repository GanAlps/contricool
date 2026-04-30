"""Unit tests for ``models.py`` — structural validation only.

Per-method invariants (PERCENT_SUM, OWED_SUM, ...) live in the
service layer; their tests are in ``test_service.py`` /
``test_create_negative.py``.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.features.transactions.models import (
    CreateTransactionRequest,
    MemberInput,
    PayerInput,
)

_ULID_A = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
_ULID_B = "01HK3W7QF6VMYG8XR3DQ7B5N6Q"


def test_create_request_accepts_minimal_equal_split() -> None:
    body = CreateTransactionRequest(
        name="Dinner",
        type="expense",
        amount=Decimal("30.00"),
        currency="USD",
        txn_date="2026-04-29",  # type: ignore[arg-type]
        split_method="equal",
        members=[MemberInput(user_id=_ULID_A), MemberInput(user_id=_ULID_B)],
        payers=[PayerInput(user_id=_ULID_A, paid_amount=Decimal("30.00"))],
    )
    assert body.amount == Decimal("30.00")
    assert body.note == ""


def test_create_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CreateTransactionRequest(
            name="x",
            type="expense",
            amount=Decimal("1.00"),
            currency="USD",
            txn_date="2026-04-29",  # type: ignore[arg-type]
            split_method="equal",
            members=[MemberInput(user_id=_ULID_A), MemberInput(user_id=_ULID_B)],
            payers=[PayerInput(user_id=_ULID_A, paid_amount=Decimal("1.00"))],
            stranger="hi",  # type: ignore[call-arg]
        )


def test_create_request_rejects_zero_amount() -> None:
    with pytest.raises(ValidationError):
        CreateTransactionRequest(
            name="x",
            type="expense",
            amount=Decimal("0"),
            currency="USD",
            txn_date="2026-04-29",  # type: ignore[arg-type]
            split_method="equal",
            members=[MemberInput(user_id=_ULID_A), MemberInput(user_id=_ULID_B)],
            payers=[PayerInput(user_id=_ULID_A, paid_amount=Decimal("1.00"))],
        )


def test_member_input_rejects_non_ulid() -> None:
    with pytest.raises(ValidationError):
        MemberInput(user_id="not-a-ulid")


def test_payer_input_rejects_zero_amount() -> None:
    with pytest.raises(ValidationError):
        PayerInput(user_id=_ULID_A, paid_amount=Decimal("0"))
