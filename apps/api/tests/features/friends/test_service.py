"""Service-layer tests covering branches that the integration tests
don't naturally exercise (defensive paths)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.features.friends import repository as repo
from app.features.friends import service
from app.features.friends.errors import UserNotFoundError

from .conftest import seed_friendship, seed_user


def test_add_meta_missing_pre_create_raises_user_not_found(
    friends_env: dict[str, object],
) -> None:
    """Defensive branch: GSI1 lookup hit but the META row is missing
    at read time (race or partial-write). The service raises
    USER_NOT_FOUND BEFORE writing the friendship row, so no orphan
    row is left behind to block future re-adds (B2 from the review)."""
    seed_user(friends_env, user_id="01HKAAA000000000000000000R", email="r@b.com", name="R")
    seed_user(friends_env, user_id="01HKBBB000000000000000000T", email="t@b.com", name="T")
    with patch.object(repo, "get_user_meta", return_value=None):
        with pytest.raises(UserNotFoundError):
            service.add_friend(
                requester_id="01HKAAA000000000000000000R",
                email="t@b.com",
            )
    # No friendship row written.
    assert not repo.friendship_exists(
        "01HKAAA000000000000000000R", "01HKBBB000000000000000000T"
    )


def test_list_skips_friend_with_missing_meta(
    friends_env: dict[str, object],
) -> None:
    """Defensive branch: the BatchGet returns nothing for a friend
    whose META row vanished. The service logs a warning and excludes
    that friend from the page."""
    requester = "01HKAAA000000000000000000R"
    friend_with_meta = "01HKFFFFFFFFFFFFFFFFFFFFFF"
    friend_without_meta = "01HKZZZZZZZZZZZZZZZZZZZZZZ"
    seed_user(friends_env, user_id=requester, email="r@b.com", name="R")
    seed_user(friends_env, user_id=friend_with_meta, email="f@b.com", name="F")
    # Don't seed META for friend_without_meta — only the friendship row.
    seed_friendship(friends_env, a_id=requester, b_id=friend_with_meta)
    seed_friendship(friends_env, a_id=requester, b_id=friend_without_meta)
    result = service.list_friends(requester_id=requester, limit=10, cursor=None)
    ids = [item.user_id for item in result.items]
    assert friend_with_meta in ids
    assert friend_without_meta not in ids


def test_balance_falls_back_to_usd_when_requester_meta_missing(
    friends_env: dict[str, object],
) -> None:
    """Defensive branch: requester is authenticated but their META row
    is unreadable. Default to USD."""
    requester = "01HKAAA000000000000000000R"
    target = "01HKBBB000000000000000000T"
    # Don't seed requester's META; do create the friendship.
    seed_user(friends_env, user_id=target, email="t@b.com", name="T")
    seed_friendship(friends_env, a_id=requester, b_id=target)
    r = service.get_balance(requester_id=requester, target_id=target)
    assert r.currency == "USD"
