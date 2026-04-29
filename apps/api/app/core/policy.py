"""Authorisation helpers.

Phase 2b ships only ``is_self`` — the simplest authz check.
``is_friend`` and ``can_edit_transaction`` are placeholders that raise
``NotImplementedError`` so accidental usage in Phases 2-3 fails loudly
rather than returning a wrong answer.

Phases 3 and 5 wire the placeholders to ``ContriCool-Users-<env>`` and
``ContriCool-Transactions-<env>`` respectively.
"""
from __future__ import annotations

from app.core.principal import Principal


def is_self(principal: Principal, target_user_id: str) -> bool:
    """True iff ``principal`` is the user identified by ``target_user_id``."""
    return principal.user_id == target_user_id


def is_friend(a_user_id: str, b_user_id: str) -> bool:
    """Phase 3 wires this to ContriCool-Users-<env>."""
    raise NotImplementedError(
        "is_friend is not implemented until Phase 3 (friends feature)."
    )


def can_edit_transaction(principal: Principal, txn: object) -> bool:
    """Phase 5 wires this to ContriCool-Transactions-<env>."""
    raise NotImplementedError(
        "can_edit_transaction is not implemented until Phase 5."
    )
