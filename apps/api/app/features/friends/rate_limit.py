"""Per-user rate-limiter for ``POST /v1/friends/add``.

Mirrors :mod:`app.features.auth.rate_limit` but keyed on the requester
``user_id`` (not on a hash of an external identifier) — friend-add is
authenticated, so the request is already bound to a Cognito subject.

One row per user::

    PK = RATE#FRIEND_ADD#<user_id>
    SK = COUNTER
    attempts_hour, hour_window_started_at, ttl

Cap: 30 add-attempts per rolling hour. Counted **before** the email
lookup so unsuccessful attempts (404, 409, 422 self-add) all count
against the cap — this closes the email-existence enumeration oracle
that "rate-limit-on-success-only" would open.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from app.core import config

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


HOUR_CAP = 30

_HOUR_SECONDS = 3600
_TTL_SECONDS = 86400  # row eligible for cleanup 24h after last touch
_MAX_RETRIES = 1


class FriendAddRateLimitExceeded(Exception):  # noqa: N818
    """Raised when the requester has hit the hour cap for friend adds."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__("friend-add rate limit exceeded")
        self.retry_after_seconds = max(1, retry_after_seconds)


_default_table: Table | None = None


def _table() -> Table:
    global _default_table
    if _default_table is None:
        cfg = config.load()
        _default_table = boto3.resource(
            "dynamodb", region_name=cfg.aws_region
        ).Table(cfg.users_table_name)
    return _default_table


def _set_table_for_tests(table: Table | None) -> None:
    global _default_table
    _default_table = table


def _key(user_id: str) -> dict[str, str]:
    return {"PK": f"RATE#FRIEND_ADD#{user_id}", "SK": "COUNTER"}


def consume_friend_add(user_id: str, *, now: int | None = None) -> None:
    """Increment the friend-add counter; raise on cap.

    ``now`` is exposed for tests to advance the clock.
    """
    now_ts = now if now is not None else int(time.time())
    table = _table()
    key = _key(user_id)

    for _ in range(_MAX_RETRIES + 1):
        existing = _get_existing(table, key)
        new_state, retry_after = _project_next(existing, now_ts)
        if retry_after is not None:
            raise FriendAddRateLimitExceeded(retry_after_seconds=retry_after)
        try:
            _commit(table, key, existing, new_state, now_ts)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                continue
            raise
    raise FriendAddRateLimitExceeded(retry_after_seconds=1)


# ---- helpers ----------------------------------------------------------


def _to_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(str(value))


def _get_existing(table: Table, key: dict[str, str]) -> dict[str, int] | None:
    response = table.get_item(Key=key, ConsistentRead=True)
    item = response.get("Item")
    if not item:
        return None
    return {
        "attempts_hour": _to_int(item.get("attempts_hour")),
        "hour_window_started_at": _to_int(item.get("hour_window_started_at")),
    }


def _project_next(
    existing: dict[str, int] | None, now_ts: int
) -> tuple[dict[str, int], int | None]:
    if existing is None:
        return ({"attempts_hour": 1, "hour_window_started_at": now_ts}, None)
    hour_started = existing["hour_window_started_at"]
    attempts_hour = existing["attempts_hour"]
    if now_ts - hour_started >= _HOUR_SECONDS:
        new_attempts = 1
        new_started = now_ts
    else:
        new_attempts = attempts_hour + 1
        new_started = hour_started
    if new_attempts > HOUR_CAP:
        retry = max(1, _HOUR_SECONDS - (now_ts - hour_started))
        return ({}, retry)
    return ({"attempts_hour": new_attempts, "hour_window_started_at": new_started}, None)


def _commit(
    table: Table,
    key: dict[str, str],
    existing: dict[str, int] | None,
    new_state: dict[str, int],
    now_ts: int,
) -> None:
    update_expr = (
        "SET attempts_hour = :ah, hour_window_started_at = :hs, #ttl_attr = :ttl"
    )
    expr_values: dict[str, object] = {
        ":ah": new_state["attempts_hour"],
        ":hs": new_state["hour_window_started_at"],
        ":ttl": now_ts + _TTL_SECONDS,
    }
    expr_names = {"#ttl_attr": "ttl"}
    if existing is None:
        condition = "attribute_not_exists(PK)"
    else:
        condition = "hour_window_started_at = :prev_hs"
        expr_values[":prev_hs"] = existing["hour_window_started_at"]
    table.update_item(
        Key=key,
        UpdateExpression=update_expr,
        ConditionExpression=condition,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,  # type: ignore[arg-type]
    )
