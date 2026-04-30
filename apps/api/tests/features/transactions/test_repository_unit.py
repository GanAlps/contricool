"""Unit tests for ``repository.py`` helpers — exercise edge branches
that the integration tests don't hit naturally."""
from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from app.features.transactions import repository as repo
from app.features.transactions.errors import NotFriendError


def _make_client_error(
    *, code: str = "TransactionCanceledException", reasons: list[dict[str, str]] | None
) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code},
            "CancellationReasons": reasons or [],
        },
        "TransactWriteItems",
    )


def test_decode_transact_error_friendship_failure_raises_not_friend() -> None:
    exc = _make_client_error(
        reasons=[
            {"Code": "ConditionalCheckFailed"},  # friendship slot 0
            {"Code": "None"},
            {"Code": "None"},
            {"Code": "None"},
            {"Code": "None"},
        ]
    )
    with pytest.raises(NotFriendError):
        repo._decode_transact_error(exc, other_member_count=1, user_id="x", key="y")


def test_decode_transact_error_unrelated_code_re_raises() -> None:
    exc = _make_client_error(code="ValidationException", reasons=[])
    with pytest.raises(ClientError):
        repo._decode_transact_error(exc, other_member_count=1, user_id="x", key="y")


def test_decode_transact_error_no_reasons_re_raises() -> None:
    exc = _make_client_error(reasons=[])
    with pytest.raises(ClientError):
        repo._decode_transact_error(exc, other_member_count=1, user_id="x", key="y")


def test_decode_transact_error_unknown_pattern_re_raises() -> None:
    """Failure that's neither friendship nor idempotency → re-raise."""
    exc = _make_client_error(
        reasons=[
            {"Code": "None"},
            {"Code": "ConditionalCheckFailed"},  # META slot — not handled
            {"Code": "None"},
        ]
    )
    with pytest.raises(ClientError):
        repo._decode_transact_error(
            exc, other_member_count=1, user_id="x", key="y"
        )


def test_get_friendship_ids_empty_input_returns_empty_set() -> None:
    assert repo.get_friendship_ids("creator", []) == set()


def test_get_user_currencies_empty_input_returns_empty_dict() -> None:
    assert repo.get_user_currencies([]) == {}


def test_batch_get_metas_chunks_at_100_keys(seed_config: object) -> None:
    """``batch_get_metas`` must split input >100 ids into multiple
    BatchGetItem calls (DDB hard limit). Reviewer-flagged blocking
    issue: ``compute_pair_balance`` can pass up to 500 ids."""

    class _StubResource:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def batch_get_item(self, *, RequestItems: dict) -> dict:  # noqa: N803  -- boto3 API kwarg shape
            (table_name,) = RequestItems.keys()
            keys = RequestItems[table_name]["Keys"]
            self.calls.append(len(keys))
            return {"Responses": {table_name: []}, "UnprocessedKeys": {}}

    stub = _StubResource()
    # Save and override the cached resource for this test.
    saved = repo._default_resource
    repo._default_resource = stub
    try:
        # 250 ids → 100 + 100 + 50.
        result = repo.batch_get_metas([f"01HK3W7QF6VMYG8XR3DQ7B5{i:03d}" for i in range(250)])
        assert result == {}
        assert stub.calls == [100, 100, 50]
    finally:
        repo._default_resource = saved


def test_batch_get_metas_retries_unprocessed_keys(seed_config: object) -> None:
    """``UnprocessedKeys`` must trigger a retry on the residual; the
    function only raises after exceeding the retry budget."""

    class _ThrottlingResource:
        def __init__(self) -> None:
            self.calls = 0

        def batch_get_item(self, *, RequestItems: dict) -> dict:  # noqa: N803  -- boto3 API kwarg shape
            (table_name,) = RequestItems.keys()
            keys = RequestItems[table_name]["Keys"]
            self.calls += 1
            # First call: leave one residual; second call: drain.
            if self.calls == 1:
                return {
                    "Responses": {table_name: []},
                    "UnprocessedKeys": {table_name: {"Keys": keys[:1]}},
                }
            return {"Responses": {table_name: []}, "UnprocessedKeys": {}}

    stub = _ThrottlingResource()
    saved = repo._default_resource
    repo._default_resource = stub
    try:
        result = repo.batch_get_metas(["01HK3W7QF6VMYG8XR3DQ7B5N6P"])
        assert result == {}
        assert stub.calls == 2  # one initial + one retry
    finally:
        repo._default_resource = saved


def test_batch_get_metas_raises_after_persistent_unprocessed(seed_config: object) -> None:
    """If retries are exhausted, the helper raises rather than
    silently returning partial data."""

    class _BrokenResource:
        def batch_get_item(self, *, RequestItems: dict) -> dict:  # noqa: N803  -- boto3 API kwarg shape
            (table_name,) = RequestItems.keys()
            keys = RequestItems[table_name]["Keys"]
            return {
                "Responses": {table_name: []},
                "UnprocessedKeys": {table_name: {"Keys": keys}},
            }

    stub = _BrokenResource()
    saved = repo._default_resource
    repo._default_resource = stub
    try:
        with pytest.raises(ClientError) as exc:
            repo.batch_get_metas(["01HK3W7QF6VMYG8XR3DQ7B5N6P"])
        assert exc.value.response["Error"]["Code"] == "ProvisionedThroughputExceededException"
    finally:
        repo._default_resource = saved
