"""Tests for the friend-add rate limiter."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from app.features.friends import rate_limit as rl


def test_first_call_creates_row(friends_env: dict[str, object]) -> None:
    rl.consume_friend_add("01J-self", now=1_000_000)
    table = friends_env["table"]
    item = table.get_item(  # type: ignore[attr-defined]
        Key={"PK": "RATE#FRIEND_ADD#01J-self", "SK": "COUNTER"}
    )["Item"]
    assert int(item["attempts_hour"]) == 1


def test_30_calls_in_same_hour_succeed(friends_env: dict[str, object]) -> None:
    base = 2_000_000
    for i in range(rl.HOUR_CAP):
        rl.consume_friend_add("01J-self", now=base + i)


def test_31st_call_raises_with_retry_after(
    friends_env: dict[str, object],
) -> None:
    base = 3_000_000
    for i in range(rl.HOUR_CAP):
        rl.consume_friend_add("01J-self", now=base + i)
    with pytest.raises(rl.FriendAddRateLimitExceeded) as exc:
        rl.consume_friend_add("01J-self", now=base + rl.HOUR_CAP)
    assert 0 < exc.value.retry_after_seconds <= 3600


def test_window_roll_resets_counter(friends_env: dict[str, object]) -> None:
    base = 4_000_000
    for i in range(rl.HOUR_CAP):
        rl.consume_friend_add("01J-self", now=base + i)
    # Advance past the hour window — counter resets to 1.
    rl.consume_friend_add("01J-self", now=base + 3601)
    table = friends_env["table"]
    item = table.get_item(  # type: ignore[attr-defined]
        Key={"PK": "RATE#FRIEND_ADD#01J-self", "SK": "COUNTER"}
    )["Item"]
    assert int(item["attempts_hour"]) == 1


def test_concurrent_loss_then_retry(friends_env: dict[str, object]) -> None:
    """First commit fails with ConditionalCheckFailed; retry succeeds."""
    rl.consume_friend_add("01J-self", now=5_000_000)
    real_commit = rl._commit
    calls: list[int] = []

    def flaky_commit(*args: object, **kwargs: object) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}},
                "UpdateItem",
            )
        return real_commit(*args, **kwargs)  # type: ignore[arg-type]

    with patch.object(rl, "_commit", side_effect=flaky_commit):
        rl.consume_friend_add("01J-self", now=5_000_001)
    assert len(calls) == 2  # one race-loss + one success


def test_independent_per_user(friends_env: dict[str, object]) -> None:
    base = 6_000_000
    for i in range(rl.HOUR_CAP):
        rl.consume_friend_add("01J-a", now=base + i)
    # User B's bucket is unaffected.
    rl.consume_friend_add("01J-b", now=base + 100)


def test_unknown_client_error_propagates(
    friends_env: dict[str, object],
) -> None:
    with patch.object(
        rl,
        "_commit",
        side_effect=ClientError(
            {"Error": {"Code": "InternalServerError"}}, "UpdateItem"
        ),
    ):
        with pytest.raises(ClientError):
            rl.consume_friend_add("01J-self", now=7_000_000)


def test_persistent_race_loss_raises_rate_limited(
    friends_env: dict[str, object],
) -> None:
    """If every retry races, surface as RateLimitExceeded with retry=1."""
    with patch.object(
        rl,
        "_commit",
        side_effect=ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
        ),
    ):
        with pytest.raises(rl.FriendAddRateLimitExceeded) as exc:
            rl.consume_friend_add("01J-self", now=8_000_000)
    assert exc.value.retry_after_seconds == 1
