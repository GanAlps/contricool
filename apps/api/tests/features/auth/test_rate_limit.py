"""Tests for ``app.features.auth.rate_limit``."""
from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from app.core.config import AppConfig
from app.features.auth import rate_limit as rl
from app.features.auth.rate_limit import (
    DAY_CAP,
    HOUR_CAP,
    RateLimitExceeded,
    consume_otp_email,
)


@pytest.fixture
def moto_users_table(
    seed_config: AppConfig, aws_credentials: None
) -> Iterator[object]:
    """Spin up a moto-backed Users table with the schema Phase 2a uses."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-west-2")
        ddb.create_table(
            TableName=seed_config.users_table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = ddb.Table(seed_config.users_table_name)
        rl._set_table_for_tests(table)
        try:
            yield table
        finally:
            rl._set_table_for_tests(None)


def _row(table: object, email: str = "alice@example.com") -> dict[str, object]:
    from app.core.lookup_hash import email_hash

    pk = f"AUTH_RATE#{email_hash(email)}"
    response = table.get_item(Key={"PK": pk, "SK": "OTP#EMAIL"})  # type: ignore[attr-defined]
    return response.get("Item") or {}


# ---- Happy paths ------------------------------------------------------


def test_first_request_creates_row(moto_users_table: object) -> None:
    consume_otp_email("alice@example.com", now=1_000_000)
    item = _row(moto_users_table)
    assert int(item["attempts_hour"]) == 1
    assert int(item["attempts_day"]) == 1
    assert int(item["hour_window_started_at"]) == 1_000_000
    assert int(item["day_window_started_at"]) == 1_000_000
    assert int(item["ttl"]) == 1_000_000 + 86400


def test_five_requests_in_one_hour_all_succeed(moto_users_table: object) -> None:
    for i in range(HOUR_CAP):
        consume_otp_email("alice@example.com", now=1_000_000 + i)
    item = _row(moto_users_table)
    assert int(item["attempts_hour"]) == HOUR_CAP


def test_sixth_request_in_one_hour_raises(moto_users_table: object) -> None:
    for i in range(HOUR_CAP):
        consume_otp_email("alice@example.com", now=1_000_000 + i)
    with pytest.raises(RateLimitExceeded) as excinfo:
        consume_otp_email("alice@example.com", now=1_000_000 + HOUR_CAP)
    assert 0 < excinfo.value.retry_after_seconds <= 3600


def test_hour_window_rolls_over(moto_users_table: object) -> None:
    for i in range(HOUR_CAP):
        consume_otp_email("alice@example.com", now=1_000_000 + i)
    # 1 hour + 1 second later → window rolls; counter resets to 1.
    consume_otp_email("alice@example.com", now=1_000_000 + 3601)
    item = _row(moto_users_table)
    assert int(item["attempts_hour"]) == 1
    assert int(item["hour_window_started_at"]) == 1_000_000 + 3601


def test_day_cap_enforced_independently_of_hour(
    moto_users_table: object,
) -> None:
    """Spread 20 requests across 4 hours; 21st trips the day cap."""
    base = 2_000_000
    sent = 0
    for hour in range(4):
        for i in range(HOUR_CAP):
            consume_otp_email("alice@example.com", now=base + hour * 3600 + i)
            sent += 1
    assert sent == DAY_CAP
    # 21st should trip day cap. Use a time well before the day window
    # rolls (still within the 86400s window from ``base``).
    with pytest.raises(RateLimitExceeded) as excinfo:
        consume_otp_email("alice@example.com", now=base + 5 * 3600)
    assert 0 < excinfo.value.retry_after_seconds <= 86400


def test_day_window_rolls_over(moto_users_table: object) -> None:
    base = 3_000_000
    for hour in range(4):
        for i in range(HOUR_CAP):
            consume_otp_email("alice@example.com", now=base + hour * 3600 + i)
    # 86400 seconds later, day rolls.
    consume_otp_email("alice@example.com", now=base + 86401)
    item = _row(moto_users_table)
    assert int(item["attempts_day"]) == 1
    assert int(item["day_window_started_at"]) == base + 86401


def test_distinct_emails_have_separate_counters(
    moto_users_table: object,
) -> None:
    for i in range(HOUR_CAP):
        consume_otp_email("alice@example.com", now=4_000_000 + i)
    # Bob is a fresh identity; should succeed.
    consume_otp_email("bob@example.com", now=4_000_000 + 100)


def test_normalised_email_collides(moto_users_table: object) -> None:
    consume_otp_email("Alice@Example.COM", now=5_000_000)
    consume_otp_email("alice@example.com", now=5_000_001)
    item = _row(moto_users_table, email="alice@example.com")
    assert int(item["attempts_hour"]) == 2


# ---- RateLimitExceeded shape ----------------------------------------


def test_rate_limit_exceeded_clamps_retry_after_to_min_1() -> None:
    e = RateLimitExceeded(retry_after_seconds=0)
    assert e.retry_after_seconds == 1


def test_rate_limit_exceeded_clamps_negative() -> None:
    e = RateLimitExceeded(retry_after_seconds=-100)
    assert e.retry_after_seconds == 1


# ---- Concurrency: ConditionalCheckFailed retry --------------------


def test_retry_on_conditional_check_failure_recovers(
    moto_users_table: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race: first commit's condition fails; second commit succeeds."""
    consume_otp_email("alice@example.com", now=6_000_000)  # seed row

    real_commit = rl._commit
    calls = {"n": 0}

    def _flaky_commit(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            from botocore.exceptions import ClientError

            raise ClientError(
                error_response={
                    "Error": {"Code": "ConditionalCheckFailedException", "Message": "x"},
                    "ResponseMetadata": {},
                },
                operation_name="UpdateItem",
            )
        return real_commit(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(rl, "_commit", _flaky_commit)
    consume_otp_email("alice@example.com", now=6_000_001)
    assert calls["n"] == 2


def test_retry_exhaustion_raises_rate_limited(
    moto_users_table: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If both attempts hit ConditionalCheckFailed, we surface RateLimitExceeded."""
    consume_otp_email("alice@example.com", now=7_000_000)

    def _always_fails(*_args: object, **_kwargs: object) -> None:
        from botocore.exceptions import ClientError

        raise ClientError(
            error_response={
                "Error": {"Code": "ConditionalCheckFailedException", "Message": "x"},
                "ResponseMetadata": {},
            },
            operation_name="UpdateItem",
        )

    monkeypatch.setattr(rl, "_commit", _always_fails)
    with pytest.raises(RateLimitExceeded):
        consume_otp_email("alice@example.com", now=7_000_001)


def test_non_condition_client_error_propagates(
    moto_users_table: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    consume_otp_email("alice@example.com", now=8_000_000)

    def _other_error(*_args: object, **_kwargs: object) -> None:
        raise ClientError(
            error_response={
                "Error": {"Code": "ResourceNotFoundException", "Message": "no such table"},
                "ResponseMetadata": {},
            },
            operation_name="UpdateItem",
        )

    monkeypatch.setattr(rl, "_commit", _other_error)
    with pytest.raises(ClientError):
        consume_otp_email("alice@example.com", now=8_000_001)


# ---- Default time + table singletons -------------------------------


def test_consume_uses_real_time_when_now_omitted(moto_users_table: object) -> None:
    consume_otp_email("alice@example.com")
    item = _row(moto_users_table)
    assert int(item["attempts_hour"]) == 1
    assert int(item["hour_window_started_at"]) > 0


def test_to_int_handles_decimal_and_str() -> None:
    """``_to_int`` accepts boto3-resource Decimal returns and string fallbacks."""
    from decimal import Decimal

    assert rl._to_int(None) == 0
    assert rl._to_int(5) == 5
    assert rl._to_int(Decimal("12")) == 12
    assert rl._to_int("7") == 7


def test_table_singleton_lazily_built(seed_config: AppConfig) -> None:
    rl._set_table_for_tests(None)
    # We don't actually call _table() here without moto active;
    # just ensure the cache is None until first call.
    assert rl._default_table is None


def test_table_lazy_init_under_moto(
    seed_config: AppConfig, aws_credentials: None
) -> None:
    """Exercise the cache-miss branch of ``_table()`` end-to-end.

    The other tests inject the table via ``_set_table_for_tests`` and
    bypass the lazy path; this test relies on the function building it
    from ``app.core.config``.
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-west-2")
        ddb.create_table(
            TableName=seed_config.users_table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        rl._set_table_for_tests(None)
        try:
            built = rl._table()
            assert built.name == seed_config.users_table_name
            # Subsequent call returns the same instance.
            assert rl._table() is built
        finally:
            rl._set_table_for_tests(None)
