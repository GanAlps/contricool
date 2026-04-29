"""Tests for ``app.core.policy``."""
from __future__ import annotations

import pytest

from app.core import policy
from app.core.principal import Principal

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


def test_is_friend_raises_not_implemented() -> None:
    """Phase 3 lands the real implementation; until then any caller that
    forgets to check the phase fails loudly rather than getting a wrong
    answer."""
    with pytest.raises(NotImplementedError, match="Phase 3"):
        policy.is_friend("a", "b")


def test_can_edit_transaction_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="Phase 5"):
        policy.can_edit_transaction(_PRINCIPAL, object())
