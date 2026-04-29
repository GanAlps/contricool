"""Tests for ``app.features.friends.repository``."""
from __future__ import annotations

import pytest

from app.features.friends import repository as repo

from .conftest import seed_friendship, seed_user


def test_find_user_by_email_hit(friends_env: dict[str, object]) -> None:
    seed_user(friends_env, user_id="01J-self", email="self@example.com", name="Self")
    assert repo.find_user_by_email("self@example.com") == "01J-self"


def test_find_user_by_email_case_insensitive(friends_env: dict[str, object]) -> None:
    seed_user(friends_env, user_id="01J-self", email="self@example.com", name="Self")
    # The email_hash function lower-cases input — same hash for both.
    assert repo.find_user_by_email("Self@Example.com") == "01J-self"


def test_find_user_by_email_miss(friends_env: dict[str, object]) -> None:
    assert repo.find_user_by_email("ghost@example.com") is None


def test_get_user_meta_hit(friends_env: dict[str, object]) -> None:
    seed_user(
        friends_env, user_id="01J-a", email="a@b.com", name="Alice", currency="INR"
    )
    meta = repo.get_user_meta("01J-a")
    assert meta is not None
    assert meta.name == "Alice"
    assert meta.currency == "INR"


def test_get_user_meta_miss(friends_env: dict[str, object]) -> None:
    assert repo.get_user_meta("01J-ghost") is None


def test_batch_get_user_metas_empty_input(friends_env: dict[str, object]) -> None:
    assert repo.batch_get_user_metas([]) == {}


def test_batch_get_user_metas_partial_hit(friends_env: dict[str, object]) -> None:
    seed_user(friends_env, user_id="01J-a", email="a@b.com", name="A")
    seed_user(friends_env, user_id="01J-b", email="b@b.com", name="B")
    out = repo.batch_get_user_metas(["01J-a", "01J-b", "01J-ghost"])
    assert "01J-a" in out
    assert "01J-b" in out
    assert "01J-ghost" not in out


def test_batch_get_user_metas_retries_on_unprocessed_keys(
    friends_env: dict[str, object],
) -> None:
    """B4: DDB BatchGetItem returns UnprocessedKeys under throttle. The
    repository must retry on the residual; otherwise friends silently
    vanish from list pages."""
    from unittest.mock import MagicMock, patch

    import boto3 as real_boto3

    fake = MagicMock()
    fake.batch_get_item.side_effect = [
        {
            "Responses": {
                "ContriCool-Users-test": [
                    {"PK": "USER#01J-a", "display_name": "A", "currency": "USD"}
                ]
            },
            "UnprocessedKeys": {
                "ContriCool-Users-test": {
                    "Keys": [{"PK": "USER#01J-b", "SK": "META"}]
                }
            },
        },
        {
            "Responses": {
                "ContriCool-Users-test": [
                    {"PK": "USER#01J-b", "display_name": "B", "currency": "USD"}
                ]
            },
            "UnprocessedKeys": {},
        },
    ]
    with patch.object(real_boto3, "resource", return_value=fake):
        out = repo.batch_get_user_metas(["01J-a", "01J-b"])
    assert set(out.keys()) == {"01J-a", "01J-b"}
    assert fake.batch_get_item.call_count == 2


def test_batch_get_user_metas_raises_when_retries_exhausted(
    friends_env: dict[str, object],
) -> None:
    """B4: persistent UnprocessedKeys → raise rather than silently drop."""
    from unittest.mock import MagicMock, patch

    import boto3 as real_boto3
    from botocore.exceptions import ClientError

    fake = MagicMock()
    fake.batch_get_item.return_value = {
        "Responses": {"ContriCool-Users-test": []},
        "UnprocessedKeys": {
            "ContriCool-Users-test": {
                "Keys": [{"PK": "USER#01J-x", "SK": "META"}]
            }
        },
    }
    with patch.object(real_boto3, "resource", return_value=fake):
        with pytest.raises(ClientError) as exc:
            repo.batch_get_user_metas(["01J-x"])
    assert "ProvisionedThroughputExceededException" in str(exc.value)
    # Bounded retries (4 attempts: 1 initial + 3 retries).
    assert fake.batch_get_item.call_count == 4


def test_create_friendship_happy(friends_env: dict[str, object]) -> None:
    when = repo.create_friendship("01J-a", "01J-b", created_by="01J-a")
    assert when is not None
    assert repo.friendship_exists("01J-a", "01J-b")
    # Order-independent existence.
    assert repo.friendship_exists("01J-b", "01J-a")


def test_create_friendship_duplicate_raises_conflict(
    friends_env: dict[str, object],
) -> None:
    repo.create_friendship("01J-a", "01J-b", created_by="01J-a")
    with pytest.raises(repo.ConflictError):
        repo.create_friendship("01J-b", "01J-a", created_by="01J-b")


def test_create_friendship_self_raises_value_error(
    friends_env: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        repo.create_friendship("01J-a", "01J-a", created_by="01J-a")


def test_delete_friendship_hit(friends_env: dict[str, object]) -> None:
    repo.create_friendship("01J-a", "01J-b", created_by="01J-a")
    assert repo.delete_friendship("01J-a", "01J-b") is True
    assert not repo.friendship_exists("01J-a", "01J-b")


def test_delete_friendship_miss(friends_env: dict[str, object]) -> None:
    assert repo.delete_friendship("01J-a", "01J-b") is False


def test_delete_friendship_self_returns_false(
    friends_env: dict[str, object],
) -> None:
    assert repo.delete_friendship("01J-a", "01J-a") is False


def test_friendship_exists_self_returns_false(
    friends_env: dict[str, object],
) -> None:
    assert repo.friendship_exists("01J-a", "01J-a") is False


def test_query_one_side_base(friends_env: dict[str, object]) -> None:
    """Friend B with id > self lives on the base index."""
    self_id = "01J-aaaa"
    seed_friendship(friends_env, a_id=self_id, b_id="01J-zzzz")
    rows, has_more = repo.query_one_side(
        self_id, side="base", fetch_limit=10, last_friend_id=None
    )
    assert [r.friend_user_id for r in rows] == ["01J-zzzz"]
    assert has_more is False


def test_query_one_side_gsi1(friends_env: dict[str, object]) -> None:
    """Friend B with id < self lives on GSI1."""
    self_id = "01J-zzzz"
    seed_friendship(friends_env, a_id=self_id, b_id="01J-aaaa")
    rows, has_more = repo.query_one_side(
        self_id, side="gsi1", fetch_limit=10, last_friend_id=None
    )
    assert [r.friend_user_id for r in rows] == ["01J-aaaa"]
    assert has_more is False


def test_query_one_side_pagination_with_cursor(
    friends_env: dict[str, object],
) -> None:
    self_id = "01J-aaaa"
    for i in range(5):
        seed_friendship(friends_env, a_id=self_id, b_id=f"01J-z{i}")
    # First page (limit 2)
    rows1, has_more1 = repo.query_one_side(
        self_id, side="base", fetch_limit=2, last_friend_id=None
    )
    assert len(rows1) == 2
    assert has_more1 is True
    # Walk forward using last_friend_id
    last_id = rows1[-1].friend_user_id
    rows2, _ = repo.query_one_side(
        self_id, side="base", fetch_limit=10, last_friend_id=last_id
    )
    assert all(r.friend_user_id > last_id for r in rows2)
    # Concatenated result is sorted ascending and has all 5.
    all_ids = [r.friend_user_id for r in rows1] + [r.friend_user_id for r in rows2]
    assert all_ids == sorted(all_ids)
    assert len(set(all_ids)) == 5


def test_query_one_side_unknown_side_raises(
    friends_env: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        repo.query_one_side(
            "01J-x", side="bogus", fetch_limit=1, last_friend_id=None
        )
