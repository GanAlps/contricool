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
