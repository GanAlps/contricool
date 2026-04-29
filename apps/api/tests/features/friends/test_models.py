"""Tests for the friends-feature Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.features.friends.models import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AddFriendRequest,
    ListFriendsQuery,
)


def test_add_friend_request_accepts_valid_email() -> None:
    r = AddFriendRequest(email="alice@example.com")
    assert r.email == "alice@example.com"


def test_add_friend_request_rejects_non_email() -> None:
    """N1: non-email inputs (incl. phone-shaped strings) → 422."""
    with pytest.raises(ValidationError):
        AddFriendRequest(email="+14155552671")
    with pytest.raises(ValidationError):
        AddFriendRequest(email="not-an-email")
    with pytest.raises(ValidationError):
        AddFriendRequest(email="")


def test_add_friend_request_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AddFriendRequest.model_validate(
            {"email": "a@b.com", "phone": "+1"}
        )


def test_list_friends_query_default_limit() -> None:
    q = ListFriendsQuery()
    assert q.limit == DEFAULT_LIMIT
    assert q.cursor is None


def test_list_friends_query_clamps_limit_too_low() -> None:
    """N12: limit < 1 → 422."""
    with pytest.raises(ValidationError):
        ListFriendsQuery(limit=0)


def test_list_friends_query_clamps_limit_too_high() -> None:
    """N11: limit > 100 → 422."""
    with pytest.raises(ValidationError):
        ListFriendsQuery(limit=MAX_LIMIT + 1)


def test_list_friends_query_accepts_max_limit() -> None:
    q = ListFriendsQuery(limit=MAX_LIMIT)
    assert q.limit == MAX_LIMIT
