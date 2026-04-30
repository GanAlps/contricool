"""Split-method math for the transactions feature.

Pure functions that compute each member's ``owed_amount`` from the
transaction's total amount and per-method inputs. ``Decimal``
arithmetic only — never floats — so monetary rounding stays
deterministic and audit-able.

Algorithms (per ``specs/06-transaction-domain/design.md``):

- ``equal``   → divide ``amount`` evenly across ``len(members)``;
  the **last member** absorbs the rounding remainder so
  ``sum(owed) == amount`` exactly.
- ``amount``  → pass through each member's input ``owed_amount``.
- ``share``   → ``owed[i] = round(amount * share[i] / sum(share), 2)``;
  last member absorbs remainder.
- ``percent`` → ``owed[i] = round(amount * percent[i] / 100, 2)``;
  last member absorbs remainder.

Inputs are assumed pre-validated by Pydantic (``models.py``) — every
member has the per-method-required field present, the lengths match,
percent sums to 100, etc. The functions here trust those invariants
and focus exclusively on the arithmetic.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Literal

SplitMethod = Literal["equal", "amount", "share", "percent"]

_TWO_PLACES = Decimal("0.01")
_HUNDRED = Decimal("100")


def _quantize_down(value: Decimal) -> Decimal:
    """Truncate ``value`` to 2 decimal places (ROUND_DOWN).

    Used for the per-member share in ``equal`` / ``share`` / ``percent``
    so the last-member-absorbs-remainder algorithm always sees a
    non-negative residual. Half-up rounding on the per-member share
    can push it above ``amount / n`` (e.g. ``0.02 / 4``), which would
    leave the absorber with a negative balance.
    """
    return value.quantize(_TWO_PLACES, rounding=ROUND_DOWN)


def _quantize(value: Decimal) -> Decimal:
    """Round ``value`` to 2 decimal places, half-up.

    Used for the final remainder absorber and for the ``amount``-method
    pass-through, where each input is already a settled monetary value.
    """
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_owed_amounts(
    *,
    method: SplitMethod,
    amount: Decimal,
    shares: list[Decimal] | None = None,
    percents: list[Decimal] | None = None,
    owed_inputs: list[Decimal] | None = None,
    member_count: int | None = None,
) -> list[Decimal]:
    """Compute the per-member owed-amount list for the chosen method.

    Parameters
    ----------
    method
        ``equal`` | ``amount`` | ``share`` | ``percent``.
    amount
        Total transaction amount (positive Decimal, 2 decimal places).
    shares
        Required for ``share``: positive ``Decimal`` per member.
    percents
        Required for ``percent``: positive ``Decimal`` per member,
        sum ≈ 100.
    owed_inputs
        Required for ``amount``: per-member explicit ``owed_amount``;
        the function returns these as-is (already validated to sum
        to ``amount``).
    member_count
        Required for ``equal``: number of members.

    Returns
    -------
    list[Decimal]
        Per-member owed amounts, in the same order as the input lists,
        with ``sum(...) == amount`` exactly.
    """
    if method == "amount":
        if owed_inputs is None:
            raise ValueError("owed_inputs required for split_method='amount'")
        return [_quantize(v) for v in owed_inputs]

    if method == "equal":
        if member_count is None or member_count < 1:
            raise ValueError("member_count >= 1 required for split_method='equal'")
        per = _quantize_down(amount / Decimal(member_count))
        result = [per] * (member_count - 1)
        result.append(_quantize(amount - sum(result, Decimal("0"))))
        return result

    if method == "share":
        if not shares:
            raise ValueError("shares required for split_method='share'")
        total = sum(shares, Decimal("0"))
        if total <= 0:
            raise ValueError("sum(shares) must be positive")
        result = [_quantize_down(amount * s / total) for s in shares[:-1]]
        result.append(_quantize(amount - sum(result, Decimal("0"))))
        return result

    if method == "percent":
        if not percents:
            raise ValueError("percents required for split_method='percent'")
        result = [_quantize_down(amount * p / _HUNDRED) for p in percents[:-1]]
        result.append(_quantize(amount - sum(result, Decimal("0"))))
        return result

    raise ValueError(f"unknown split method {method!r}")


def settlement_owed_amounts(
    *,
    amount: Decimal,
    payer_index: int,
) -> list[Decimal]:
    """Settlement helper: 2-member, 1-payer special case.

    The payer's ``owed_amount`` is 0; the non-payer's is ``amount``.
    Returned list is length 2 in member order.
    """
    if payer_index not in (0, 1):
        raise ValueError("payer_index must be 0 or 1 for a settlement")
    quantized = _quantize(amount)
    if payer_index == 0:
        return [Decimal("0.00"), quantized]
    return [quantized, Decimal("0.00")]
