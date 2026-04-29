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


def test_add_friend_request_accepts_string_input() -> None:
    """The schema is permissive ``str``; the service distinguishes
    phone-shaped (400 INVALID_IDENTIFIER) from malformed-email (422
    VALIDATION_ERROR). See test_add for the integration tests."""
    r = AddFriendRequest(email="alice@example.com")
    assert r.email == "alice@example.com"
    # Phone-shaped accepted at the model layer — service rejects.
    r2 = AddFriendRequest(email="+14155552671")
    assert r2.email == "+14155552671"


def test_add_friend_request_rejects_empty_string() -> None:
    """min_length=1 keeps empty payloads out without rejecting valid emails."""
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
