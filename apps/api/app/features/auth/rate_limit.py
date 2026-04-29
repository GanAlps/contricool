"""OTP rate-limiter backed by ``ContriCool-Users-<env>``.

One DDB row per email identity, shared across the email-OTP send paths
(resend-email-code + forgot-password):

::

    PK = AUTH_RATE#<email-hash>
    SK = OTP#EMAIL
    attempts_hour, hour_window_started_at,
    attempts_day,  day_window_started_at,
    ttl                                  # now + 24h, DDB TTL auto-cleans

Caps: 5 sends/hour, 20 sends/day per email.

Concurrency model: read-then-conditional-update. The condition pins the
``*_window_started_at`` values from the read; a concurrent caller that
raced ahead will have advanced the windows or counters, our update
fails, and we retry the whole read-update once. After two consecutive
race losses we surface a 503-style operational error — at single-digit
RPS for OTP traffic, this should essentially never happen.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

from app.core import config
from app.core.lookup_hash import email_hash

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


HOUR_CAP = 5
DAY_CAP = 20

_HOUR_SECONDS = 3600
_DAY_SECONDS = 86400
_TTL_SECONDS = _DAY_SECONDS  # row eligible for cleanup 24h after last touch
_MAX_RETRIES = 1  # retry once after a race loss


class RateLimitExceeded(Exception):  # noqa: N818  -- name fixed in design.md
    """Raised when the caller has hit the hour or day cap.

    ``retry_after_seconds`` is the suggested ``Retry-After`` value for
    the HTTP response — the smaller of (hour-window remaining,
    day-window remaining), bounded ≥ 1.
    """

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
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
    """Inject a moto-backed Table for tests."""
    global _default_table
    _default_table = table


def _key(email: str) -> dict[str, str]:
    return {"PK": f"AUTH_RATE#{email_hash(email)}", "SK": "OTP#EMAIL"}


def consume_otp_email(email: str, *, now: int | None = None) -> None:
    """Increment OTP counters; raise :class:`RateLimitExceeded` at cap.

    ``now`` is exposed for tests to manipulate the clock.
    """
    now_ts = now if now is not None else int(time.time())
    table = _table()
    key = _key(email)

    for _ in range(_MAX_RETRIES + 1):
        existing = _get_existing(table, key)
        new_state, retry_after = _project_next_state(existing, now_ts)
        if retry_after is not None:
            raise RateLimitExceeded(retry_after_seconds=retry_after)
        try:
            _commit(table, key, existing, new_state, now_ts)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                continue
            raise
    raise RateLimitExceeded(retry_after_seconds=1)


# ---- Helpers -----------------------------------------------------------


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
        "attempts_day": _to_int(item.get("attempts_day")),
        "day_window_started_at": _to_int(item.get("day_window_started_at")),
    }


def _project_next_state(
    existing: dict[str, int] | None, now_ts: int
) -> tuple[dict[str, int], int | None]:
    """Compute ``(new_state, retry_after_or_None)``.

    ``retry_after_or_None`` is set when the projection would exceed a
    cap, signalling the caller should raise without committing.
    """
    if existing is None:
        return (
            {
                "attempts_hour": 1,
                "hour_window_started_at": now_ts,
                "attempts_day": 1,
                "day_window_started_at": now_ts,
            },
            None,
        )

    hour_started = existing["hour_window_started_at"]
    day_started = existing["day_window_started_at"]
    attempts_hour = existing["attempts_hour"]
    attempts_day = existing["attempts_day"]

    if now_ts - hour_started >= _HOUR_SECONDS:
        new_attempts_hour = 1
        new_hour_started = now_ts
    else:
        new_attempts_hour = attempts_hour + 1
        new_hour_started = hour_started

    if now_ts - day_started >= _DAY_SECONDS:
        new_attempts_day = 1
        new_day_started = now_ts
    else:
        new_attempts_day = attempts_day + 1
        new_day_started = day_started

    if new_attempts_hour > HOUR_CAP:
        retry = max(1, _HOUR_SECONDS - (now_ts - hour_started))
        return ({}, retry)
    if new_attempts_day > DAY_CAP:
        retry = max(1, _DAY_SECONDS - (now_ts - day_started))
        return ({}, retry)

    return (
        {
            "attempts_hour": new_attempts_hour,
            "hour_window_started_at": new_hour_started,
            "attempts_day": new_attempts_day,
            "day_window_started_at": new_day_started,
        },
        None,
    )


def _commit(
    table: Table,
    key: dict[str, str],
    existing: dict[str, int] | None,
    new_state: dict[str, int],
    now_ts: int,
) -> None:
    """Conditional UpdateItem that pins the windows we read.

    Two condition shapes:
    - First write (``existing is None``): ``attribute_not_exists(PK)``.
    - Subsequent: pin both ``*_window_started_at`` to the read values,
      so a concurrent advance fails the condition and we retry.
    """
    update_expr = (
        "SET attempts_hour = :ah, "
        "hour_window_started_at = :hs, "
        "attempts_day = :ad, "
        "day_window_started_at = :ds, "
        "#ttl_attr = :ttl"
    )
    expr_values: dict[str, object] = {
        ":ah": new_state["attempts_hour"],
        ":hs": new_state["hour_window_started_at"],
        ":ad": new_state["attempts_day"],
        ":ds": new_state["day_window_started_at"],
        ":ttl": now_ts + _TTL_SECONDS,
    }
    expr_names = {"#ttl_attr": "ttl"}

    if existing is None:
        condition = "attribute_not_exists(PK)"
    else:
        condition = (
            "hour_window_started_at = :prev_hs AND "
            "day_window_started_at = :prev_ds"
        )
        expr_values[":prev_hs"] = existing["hour_window_started_at"]
        expr_values[":prev_ds"] = existing["day_window_started_at"]

    table.update_item(
        Key=key,
        UpdateExpression=update_expr,
        ConditionExpression=condition,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,  # type: ignore[arg-type]
    )
