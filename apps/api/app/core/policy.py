"""Authorisation helpers.

Phase 2b shipped ``is_self``. Phase 3a wires ``is_friend`` to the
canonical-pair friendship row on ``ContriCool-Users-<env>`` via the
friends-feature repository — this keeps the friendship-row schema
encapsulated in one place (Phase 4 transactions reuse this helper
without re-implementing the lookup).

``can_edit_transaction`` stays a placeholder until Phase 5.
"""
from __future__ import annotations

from app.core.principal import Principal


def is_self(principal: Principal, target_user_id: str) -> bool:
    """True iff ``principal`` is the user identified by ``target_user_id``."""
    return principal.user_id == target_user_id


def is_friend(a_user_id: str, b_user_id: str) -> bool:
    """True iff the two users have an active friendship.

    Self-pair always returns False (you're never your own friend).
    """
    if a_user_id == b_user_id:
        return False
    # Local import: avoids a circular dependency at module load
    # (friends.repository → app.core.config → … → app.core.policy).
    from app.features.friends import repository as friends_repo

    return friends_repo.friendship_exists(a_user_id, b_user_id)


def can_edit_transaction(principal: Principal, txn: object) -> bool:
    """Phase 5 wires this to ContriCool-Transactions-<env>."""
    raise NotImplementedError(
        "can_edit_transaction is not implemented until Phase 5."
    )
