"""Pair-balance computation for the transactions feature.

Pure functions — no DDB, no FastAPI. Given the META + MEMBER rows for
the set of transactions involving both users (pre-fetched by the
caller), produce the **net balance** that one user has with the other.

Sign convention from the *requester*'s perspective:

- ``net > 0``  → friend owes requester (positive = "you're owed").
- ``net < 0``  → requester owes friend (negative = "you owe").
- ``abs(net) < 0.01`` → settled.

The math (per ``specs/06-transaction-domain/design.md`` §"Balance
computation"):

For each transaction ``t`` containing both users, with total paid
``T = sum(p.paid_amount)``:

- For every payer ``p`` and every non-payer ``m`` in the transaction,
  ``m`` owes ``p``: ``share = m.owed_amount * p.paid_amount / T``.

Aggregating the pair (requester=R, friend=F) over all such pairs:

- When ``R`` paid and ``F`` is a non-payer member:
  contribution to ``R``'s balance with ``F`` = ``+ F.owed_amount * R.paid_amount / T``.
- When ``F`` paid and ``R`` is a non-payer member:
  contribution = ``- R.owed_amount * F.paid_amount / T``.

Rounding: the running sum is left in raw ``Decimal`` form; the final
returned ``net`` is rounded half-up to 2 decimal places. ``Decimal``
math throughout — never floats.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

SettlementStatus = Literal["settled", "friend_owes", "you_owe"]

_TWO = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class TxnSummary:
    """Just the fields ``compute_pair_balance`` reads."""

    txn_id: str
    amount: Decimal
    payers: list[tuple[str, Decimal]]  # (user_id, paid_amount)
    members: dict[str, Decimal]  # user_id → owed_amount
    txn_date: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BalanceResult:
    net: Decimal
    settlement_status: SettlementStatus
    last_transaction_at: datetime | None


def compute_pair_balance(
    *, my_id: str, friend_id: str, txns: list[TxnSummary]
) -> BalanceResult:
    """Compute the net balance of ``my_id`` with ``friend_id``.

    Only transactions that include both users contribute. Soft-
    deleted transactions must be filtered out by the caller; this
    function trusts the input list.
    """
    if my_id == friend_id:
        raise ValueError("cannot compute balance with self")

    raw_net = _ZERO
    last_at: datetime | None = None
    for t in txns:
        if my_id not in t.members or friend_id not in t.members:
            continue
        if t.created_at is not None and (last_at is None or t.created_at > last_at):
            last_at = t.created_at
        total_paid = sum((amt for _, amt in t.payers), _ZERO)
        if total_paid <= 0:  # pragma: no cover - guarded by validation
            continue
        for payer_id, paid in t.payers:
            if payer_id == my_id:
                # I paid; friend owes me their share of my contribution.
                friend_owed = t.members[friend_id]
                if friend_owed > 0 and friend_id != payer_id:
                    raw_net += friend_owed * paid / total_paid
            elif payer_id == friend_id:
                # Friend paid; I owe friend my share of their contribution.
                my_owed = t.members[my_id]
                if my_owed > 0 and my_id != payer_id:
                    raw_net -= my_owed * paid / total_paid
            # Other payers don't move our pair's balance.

    net = raw_net.quantize(_TWO, rounding=ROUND_HALF_UP)
    if abs(net) < _TWO:
        return BalanceResult(
            net=_ZERO,
            settlement_status="settled",
            last_transaction_at=last_at,
        )
    return BalanceResult(
        net=net,
        settlement_status="friend_owes" if net > 0 else "you_owe",
        last_transaction_at=last_at,
    )
