"""Unit tests for ``splits.py``."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.features.transactions.splits import (
    compute_owed_amounts,
    settlement_owed_amounts,
)


def D(s: str) -> Decimal:  # noqa: N802 - terse helper
    return Decimal(s)


def test_equal_split_two_members_clean() -> None:
    out = compute_owed_amounts(method="equal", amount=D("10.00"), member_count=2)
    assert out == [D("5.00"), D("5.00")]
    assert sum(out) == D("10.00")


def test_equal_split_three_members_with_rounding_remainder() -> None:
    out = compute_owed_amounts(method="equal", amount=D("10.00"), member_count=3)
    # 10 / 3 = 3.33, last absorbs the remainder.
    assert out == [D("3.33"), D("3.33"), D("3.34")]
    assert sum(out) == D("10.00")


def test_equal_split_five_members_with_rounding_remainder() -> None:
    out = compute_owed_amounts(method="equal", amount=D("100.00"), member_count=5)
    assert sum(out) == D("100.00")
    assert all(v >= D("19.99") and v <= D("20.01") for v in out)


def test_equal_split_single_member() -> None:
    out = compute_owed_amounts(method="equal", amount=D("7.13"), member_count=1)
    assert out == [D("7.13")]


def test_amount_split_passthrough() -> None:
    out = compute_owed_amounts(
        method="amount",
        amount=D("9.00"),
        owed_inputs=[D("3.00"), D("2.50"), D("3.50")],
    )
    assert out == [D("3.00"), D("2.50"), D("3.50")]


def test_share_split_proportional_with_remainder() -> None:
    # 100 split as 1:2:1 → 25, 50, 25.
    out = compute_owed_amounts(
        method="share",
        amount=D("100.00"),
        shares=[D("1"), D("2"), D("1")],
    )
    assert sum(out) == D("100.00")
    assert out == [D("25.00"), D("50.00"), D("25.00")]


def test_share_split_remainder_absorbed_by_last() -> None:
    # 10 split as 1:1:1 = 3.33 each, last absorbs to 3.34.
    out = compute_owed_amounts(
        method="share",
        amount=D("10.00"),
        shares=[D("1"), D("1"), D("1")],
    )
    assert sum(out) == D("10.00")
    assert out == [D("3.33"), D("3.33"), D("3.34")]


def test_percent_split_clean() -> None:
    out = compute_owed_amounts(
        method="percent",
        amount=D("200.00"),
        percents=[D("25"), D("25"), D("50")],
    )
    assert out == [D("50.00"), D("50.00"), D("100.00")]
    assert sum(out) == D("200.00")


def test_percent_split_remainder_absorbed_by_last() -> None:
    out = compute_owed_amounts(
        method="percent",
        amount=D("10.00"),
        percents=[D("33.33"), D("33.33"), D("33.34")],
    )
    assert sum(out) == D("10.00")


def test_settlement_payer_at_index_0() -> None:
    out = settlement_owed_amounts(amount=D("25.00"), payer_index=0)
    assert out == [D("0.00"), D("25.00")]


def test_settlement_payer_at_index_1() -> None:
    out = settlement_owed_amounts(amount=D("25.00"), payer_index=1)
    assert out == [D("25.00"), D("0.00")]


def test_settlement_invalid_payer_index_raises() -> None:
    with pytest.raises(ValueError, match="payer_index"):
        settlement_owed_amounts(amount=D("25.00"), payer_index=2)


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="unknown split method"):
        compute_owed_amounts(method="bogus", amount=D("10.00"), member_count=2)  # type: ignore[arg-type]


def test_amount_method_requires_owed_inputs() -> None:
    with pytest.raises(ValueError, match="owed_inputs"):
        compute_owed_amounts(method="amount", amount=D("1"))


def test_equal_method_requires_member_count() -> None:
    with pytest.raises(ValueError, match="member_count"):
        compute_owed_amounts(method="equal", amount=D("1"))


def test_share_method_requires_shares() -> None:
    with pytest.raises(ValueError, match="shares"):
        compute_owed_amounts(method="share", amount=D("1"))


def test_share_method_zero_total_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        compute_owed_amounts(method="share", amount=D("1"), shares=[D("0"), D("0")])


def test_percent_method_requires_percents() -> None:
    with pytest.raises(ValueError, match="percents"):
        compute_owed_amounts(method="percent", amount=D("1"))
