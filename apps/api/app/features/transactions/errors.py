"""Per-transactions-feature error classes.

Subclass :class:`app.features.auth.errors.AuthError` so the existing
exception handler serialises them through the same envelope and the
OpenAPI emit picks up the codes consistently.
"""
from __future__ import annotations

from app.features.auth.errors import AuthError


class NotFoundError(AuthError):
    """The transaction doesn't exist or the requester isn't a member.

    Uniform 404 mask — non-member callers can't tell the difference
    between "doesn't exist" and "not yours" (CLAUDE.md red-line 3
    entry: wrong-user authorization → 404).
    """

    def __init__(self) -> None:
        super().__init__(
            code="NOT_FOUND",
            http_status=404,
            message="No such transaction.",
        )


class NotFriendError(AuthError):
    """A non-creator member is not a current friend of the creator."""

    def __init__(self) -> None:
        super().__init__(
            code="NOT_FRIEND",
            http_status=422,
            message="One or more members are not your friend.",
        )


class CurrencyMismatchError(AuthError):
    """A member's currency differs from the transaction's currency."""

    def __init__(self) -> None:
        super().__init__(
            code="CURRENCY_MISMATCH",
            http_status=422,
            message="All members must share the transaction's currency.",
        )


class SelfNotMemberError(AuthError):
    """Creator must include themselves in ``members``."""

    def __init__(self) -> None:
        super().__init__(
            code="SELF_NOT_MEMBER",
            http_status=422,
            message="You must be one of the transaction's members.",
        )


class MemberCountError(AuthError):
    """Member list out of bounds."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(code=code, http_status=422, message=message)


class PayerNotMemberError(AuthError):
    """A payer isn't in the transaction's member list."""

    def __init__(self) -> None:
        super().__init__(
            code="PAYER_NOT_MEMBER",
            http_status=422,
            message="Every payer must be one of the transaction's members.",
        )


class PaidSumError(AuthError):
    """Sum of ``payers[*].paid_amount`` ≠ ``amount``."""

    def __init__(self) -> None:
        super().__init__(
            code="PAID_SUM",
            http_status=422,
            message="Sum of paid amounts must equal the transaction amount.",
        )


class OwedSumError(AuthError):
    """``split_method='amount'``: sum of owed_amounts ≠ amount."""

    def __init__(self) -> None:
        super().__init__(
            code="OWED_SUM",
            http_status=422,
            message="Sum of owed amounts must equal the transaction amount.",
        )


class PercentSumError(AuthError):
    """``split_method='percent'``: sum of percents not within 100±0.01."""

    def __init__(self) -> None:
        super().__init__(
            code="PERCENT_SUM",
            http_status=422,
            message="Percents must sum to 100.",
        )


class InvalidAmountError(AuthError):
    """Non-positive amount."""

    def __init__(self) -> None:
        super().__init__(
            code="INVALID_AMOUNT",
            http_status=422,
            message="Amount must be a positive number.",
        )


class InvalidDateError(AuthError):
    """Date out of accepted window."""

    def __init__(self, *, message: str) -> None:
        super().__init__(
            code="INVALID_DATE",
            http_status=422,
            message=message,
        )


class IdempotencyKeyRequiredError(AuthError):
    """``POST /v1/transactions`` invoked without ``Idempotency-Key`` header."""

    def __init__(self) -> None:
        super().__init__(
            code="IDEMPOTENCY_KEY_REQUIRED",
            http_status=400,
            message="Idempotency-Key header is required.",
        )


class IdempotencyKeyReusedError(AuthError):
    """Same key, same user, but a different request body."""

    def __init__(self) -> None:
        super().__init__(
            code="IDEMPOTENCY_KEY_REUSED",
            http_status=409,
            message="Idempotency-Key reused with a different request body.",
        )


class ValidationFailedError(AuthError):
    """Manual validation failure — used for non-Pydantic field errors."""

    def __init__(self, *, field: str, issue: str) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            http_status=422,
            message="Request failed validation.",
            details=[{"field": field, "issue": issue}],
        )


class InvalidCursorError(AuthError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CURSOR",
            http_status=422,
            message="Pagination cursor is invalid.",
        )


class ForbiddenError(AuthError):
    """Non-creator tried to mutate a transaction (edit / delete / restore).

    Distinct from the 404 mask used for non-members: a member who
    isn't the creator gets a useful error code so the client can
    render a precise "you can't edit this" message. Non-members
    still get 404 (red-line 3 — never confirm existence to outsiders).
    """

    def __init__(self) -> None:
        super().__init__(
            code="FORBIDDEN",
            http_status=403,
            message="Only the creator can modify this transaction.",
        )


class PreconditionFailedError(AuthError):
    """``If-Match`` header didn't match the current ``updated_at``.

    Optimistic concurrency: a stale edit from a second tab loses to
    the first writer. The client refetches and re-attempts.
    """

    def __init__(self) -> None:
        super().__init__(
            code="PRECONDITION_FAILED",
            http_status=412,
            message="The transaction was modified elsewhere. Refresh and try again.",
        )


class GoneError(AuthError):
    """Soft-deleted transaction is past the 30-day restore window.

    410 GONE is the precise HTTP semantic — the resource existed but
    is no longer recoverable.
    """

    def __init__(self) -> None:
        super().__init__(
            code="GONE",
            http_status=410,
            message="The 30-day restore window has expired.",
        )


class NotDeletedError(AuthError):
    """``POST :restore`` on a transaction that isn't soft-deleted."""

    def __init__(self) -> None:
        super().__init__(
            code="NOT_DELETED",
            http_status=422,
            message="Transaction is not deleted.",
        )
