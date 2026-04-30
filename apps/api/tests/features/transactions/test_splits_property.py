"""Hypothesis property tests for ``splits.py`` — the core safety net.

The non-negotiable invariant: ``sum(compute_owed_amounts(...)) == amount``
exactly, for every valid input across every split method. If a future
refactor breaks this, balances drift silently — the worst-case bug for
a financial app. These tests keep the algorithm honest under arbitrary
input shapes.
"""
from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.features.transactions.splits import compute_owed_amounts

# Amount: 0.01 .. 99,999,999.99 with 2 decimal places.
_AMOUNT = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Member count: 2..10 (Design 6 cap).
_MEMBER_COUNT = st.integers(min_value=2, max_value=10)

# Per-member share: positive Decimal, bounded.
_SHARE = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@given(amount=_AMOUNT, n=_MEMBER_COUNT)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_equal_split_sums_to_amount(amount: Decimal, n: int) -> None:
    out = compute_owed_amounts(method="equal", amount=amount, member_count=n)
    assert len(out) == n
    assert sum(out) == amount
    assert all(v >= 0 for v in out)
    # 2-decimal places preserved.
    assert all(v == v.quantize(Decimal("0.01")) for v in out)


@given(amount=_AMOUNT, n=_MEMBER_COUNT, data=st.data())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_share_split_sums_to_amount(
    amount: Decimal, n: int, data: st.DataObject
) -> None:
    shares = data.draw(st.lists(_SHARE, min_size=n, max_size=n))
    out = compute_owed_amounts(method="share", amount=amount, shares=shares)
    assert len(out) == n
    assert sum(out) == amount
    assert all(v == v.quantize(Decimal("0.01")) for v in out)


@given(amount=_AMOUNT, n=_MEMBER_COUNT, data=st.data())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_percent_split_sums_to_amount(
    amount: Decimal, n: int, data: st.DataObject
) -> None:
    # Build a percent vector summing to 100 (within the 2-decimal grid).
    # Strategy: draw n-1 percents in [0.01, 99.99 / (n-1)], compute the
    # last as 100 - sum(others). Reject infeasible draws.
    if n == 1:  # not used at MVP but defensive
        percents = [Decimal("100.00")]
    else:
        head = data.draw(
            st.lists(
                st.decimals(
                    min_value=Decimal("0.01"),
                    max_value=Decimal("99.99"),
                    places=2,
                ),
                min_size=n - 1,
                max_size=n - 1,
            )
        )
        head_sum = sum(head, Decimal("0"))
        # Filter out vectors whose head already exceeds 100.
        if head_sum > Decimal("99.99"):
            return
        last = Decimal("100.00") - head_sum
        if last < Decimal("0.01"):
            return
        percents = [*head, last]
        assert sum(percents) == Decimal("100.00")
    out = compute_owed_amounts(method="percent", amount=amount, percents=percents)
    assert len(out) == n
    assert sum(out) == amount
    assert all(v >= 0 for v in out)
    assert all(v == v.quantize(Decimal("0.01")) for v in out)


@given(amount=_AMOUNT, n=_MEMBER_COUNT, data=st.data())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_amount_split_passthrough_preserves_sum(
    amount: Decimal, n: int, data: st.DataObject
) -> None:
    # Build an owed_inputs vector summing exactly to amount: take n-1
    # values in [0, amount/(n-1)], compute the last as remainder.
    head = data.draw(
        st.lists(
            st.decimals(
                min_value=Decimal("0.00"),
                max_value=amount,
                places=2,
            ),
            min_size=n - 1,
            max_size=n - 1,
        )
    )
    head_sum = sum(head, Decimal("0"))
    if head_sum > amount:
        return
    last = amount - head_sum
    inputs = [*head, last]
    out = compute_owed_amounts(
        method="amount", amount=amount, owed_inputs=inputs
    )
    assert sum(out) == amount
    assert all(v == v.quantize(Decimal("0.01")) for v in out)
