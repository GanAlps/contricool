"""Tests for ``app.core.policy``."""
from __future__ import annotations

import pytest

from app.core import policy
from app.core.principal import Principal
from tests.features.friends.conftest import friends_env  # noqa: F401  -- pytest fixture

_PRINCIPAL = Principal.model_construct(
    user_id="01HK3W7QF6VMYG8XR3DQ7B5N6P",
    email="alice@example.com",
    display_name="Alice",
    groups=[],
    token_use="id",
)


def test_is_self_true_when_user_id_matches() -> None:
    assert policy.is_self(_PRINCIPAL, "01HK3W7QF6VMYG8XR3DQ7B5N6P") is True


def test_is_self_false_when_user_id_differs() -> None:
    assert policy.is_self(_PRINCIPAL, "01HK3W7QF6VMYG8XR3DQ7B5N6Q") is False


def test_is_friend_self_pair_is_false(friends_env: dict[str, object]) -> None:  # noqa: F811
    """Phase 3a invariant: you're never your own friend."""
    assert policy.is_friend("01J-x", "01J-x") is False


def test_is_friend_no_friendship_is_false(friends_env: dict[str, object]) -> None:  # noqa: F811
    assert policy.is_friend("01J-a", "01J-b") is False


def test_is_friend_existing_friendship_is_true(
    friends_env: dict[str, object],  # noqa: F811
) -> None:
    from app.features.friends import repository as friends_repo

    friends_repo.create_friendship("01J-a", "01J-b", created_by="01J-a")
    assert policy.is_friend("01J-a", "01J-b") is True
    # Order-independent.
    assert policy.is_friend("01J-b", "01J-a") is True


def test_can_edit_transaction_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 5"):
        policy.can_edit_transaction(_PRINCIPAL, object())
