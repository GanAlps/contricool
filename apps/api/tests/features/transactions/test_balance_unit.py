"""Unit tests for ``balance.py``."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.features.transactions.balance import (
    BalanceResult,
    TxnSummary,
    compute_pair_balance,
)


def D(s: str) -> Decimal:  # noqa: N802
    return Decimal(s)


def _txn(
    txn_id: str,
    *,
    amount: Decimal,
    payers: list[tuple[str, Decimal]],
    members: dict[str, Decimal],
    when: datetime | None = None,
) -> TxnSummary:
    return TxnSummary(
        txn_id=txn_id,
        amount=amount,
        payers=payers,
        members=members,
        txn_date="2026-04-29",
        created_at=when,
    )


def test_no_transactions_means_settled() -> None:
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[])
    assert out == BalanceResult(
        net=D("0.00"), settlement_status="settled", last_transaction_at=None
    )


def test_single_equal_split_creator_pays_full() -> None:
    """A pays $30 dinner for A,B,C equal split. A's balance with B is +10
    (B owes A)."""
    t = _txn(
        "t1",
        amount=D("30.00"),
        payers=[("A", D("30.00"))],
        members={"A": D("10.00"), "B": D("10.00"), "C": D("10.00")},
    )
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[t])
    assert out.net == D("10.00")
    assert out.settlement_status == "friend_owes"


def test_single_equal_split_b_perspective() -> None:
    """B's balance with A is the mirror of A's with B (-10)."""
    t = _txn(
        "t1",
        amount=D("30.00"),
        payers=[("A", D("30.00"))],
        members={"A": D("10.00"), "B": D("10.00"), "C": D("10.00")},
    )
    out = compute_pair_balance(my_id="B", friend_id="A", txns=[t])
    assert out.net == D("-10.00")
    assert out.settlement_status == "you_owe"


def test_multi_payer_proportional_split() -> None:
    """A and C jointly paid; their shares of B's debt are proportional."""
    t = _txn(
        "t1",
        amount=D("30.00"),
        payers=[("A", D("20.00")), ("C", D("10.00"))],
        members={"A": D("10.00"), "B": D("10.00"), "C": D("10.00")},
    )
    # A paid 20/30 of B's 10 = 6.67; balance A vs B = +6.67.
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[t])
    assert out.net == D("6.67")


def test_settlement_zeroes_balance() -> None:
    """A paid 30 dinner equally; later C paid A $10 settlement → balance settled."""
    dinner = _txn(
        "t1",
        amount=D("30.00"),
        payers=[("A", D("30.00"))],
        members={"A": D("10.00"), "B": D("10.00"), "C": D("10.00")},
    )
    settle = _txn(
        "t2",
        amount=D("10.00"),
        payers=[("C", D("10.00"))],
        # Settlement: payer's owed=0, non-payer's owed=amount.
        members={"C": D("0.00"), "A": D("10.00")},
    )
    out = compute_pair_balance(my_id="A", friend_id="C", txns=[dinner, settle])
    assert out.net == D("0.00")
    assert out.settlement_status == "settled"


def test_self_balance_raises() -> None:
    with pytest.raises(ValueError, match="self"):
        compute_pair_balance(my_id="A", friend_id="A", txns=[])


def test_skips_transactions_missing_one_member() -> None:
    t = _txn(
        "t1",
        amount=D("10.00"),
        payers=[("A", D("10.00"))],
        members={"A": D("5.00"), "C": D("5.00")},  # B not in this txn
    )
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[t])
    assert out.net == D("0.00")
    assert out.settlement_status == "settled"


def test_last_transaction_at_returns_max_timestamp() -> None:
    earlier = datetime(2026, 4, 1, tzinfo=UTC)
    later = datetime(2026, 4, 28, tzinfo=UTC)
    t1 = _txn(
        "t1",
        amount=D("10.00"),
        payers=[("A", D("10.00"))],
        members={"A": D("5.00"), "B": D("5.00")},
        when=earlier,
    )
    t2 = _txn(
        "t2",
        amount=D("20.00"),
        payers=[("A", D("20.00"))],
        members={"A": D("10.00"), "B": D("10.00")},
        when=later,
    )
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[t1, t2])
    assert out.last_transaction_at == later
    assert out.net == D("15.00")


def test_chain_of_transactions_aggregates() -> None:
    """A paid 30; later B paid 60. Net should reflect both."""
    t1 = _txn(
        "t1",
        amount=D("30.00"),
        payers=[("A", D("30.00"))],
        members={"A": D("15.00"), "B": D("15.00")},
    )
    t2 = _txn(
        "t2",
        amount=D("60.00"),
        payers=[("B", D("60.00"))],
        members={"A": D("30.00"), "B": D("30.00")},
    )
    # A vs B: +15 (t1) + (-30) (t2) = -15. A owes B 15.
    out = compute_pair_balance(my_id="A", friend_id="B", txns=[t1, t2])
    assert out.net == D("-15.00")
    assert out.settlement_status == "you_owe"
