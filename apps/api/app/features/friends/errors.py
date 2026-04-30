"""Per-friend-feature error classes.

Each subclasses :class:`app.features.auth.errors.AuthError` (renamed
upstream as the project's stable feature-error base) so the existing
exception handler in :func:`app.features.auth.errors.auth_error_handler`
serialises them through the same envelope.
"""
from __future__ import annotations

from app.features.auth.errors import AuthError


class InvalidIdentifierError(AuthError):
    """Friend-add called with a non-email identifier (CONSTRAINTS.md
    "email-only at MVP" — phone-shaped strings are rejected upfront
    with a distinct 400 code so the client renders a precise
    "email only" message rather than a generic validation error)."""

    def __init__(self) -> None:
        super().__init__(
            code="INVALID_IDENTIFIER",
            http_status=400,
            message="Friends are added by email only.",
        )


class UserNotFoundError(AuthError):
    """No matching user / no matching friendship.

    Reused for both (a) ``add`` against an unregistered email and
    (b) ``remove``/``balance`` for a non-friend — uniform 404 keeps
    the privacy story tight (a non-friend can't tell whether a user
    exists from this endpoint, only that "they aren't your friend").
    """

    def __init__(self) -> None:
        super().__init__(
            code="USER_NOT_FOUND",
            http_status=404,
            message="No such user or friendship.",
        )


class ConflictError(AuthError):
    """Friend-add when the friendship already exists."""

    def __init__(self) -> None:
        super().__init__(
            code="CONFLICT",
            http_status=409,
            message="Friendship already exists.",
        )


class SelfAddForbiddenError(AuthError):
    """``POST /v1/friends/add`` resolved to the requester themselves."""

    def __init__(self) -> None:
        super().__init__(
            code="SELF_ADD_FORBIDDEN",
            http_status=422,
            message="You can't add yourself as a friend.",
        )


class SelfActionForbiddenError(AuthError):
    """``DELETE`` or ``GET /balance`` for the requester's own user_id."""

    def __init__(self) -> None:
        super().__init__(
            code="SELF_ACTION_FORBIDDEN",
            http_status=422,
            message="You can't perform this action on yourself.",
        )


class InvalidCursorError(AuthError):
    """Tampered, expired, or cross-user pagination cursor."""

    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CURSOR",
            http_status=422,
            message="Pagination cursor is invalid.",
        )


class RateLimitedError(AuthError):
    """Per-user friend-add cap (30/hour) hit."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__(
            code="RATE_LIMITED",
            http_status=429,
            message="Too many friend-add attempts. Please wait and try again.",
            retry_after_seconds=retry_after_seconds,
        )


class BalanceNotSettledError(AuthError):
    """``DELETE /v1/friends/{user_id}`` blocked because the requester
    still has a non-zero balance with the friend.

    409 because the friendship row still exists and the operation is
    not retryable until the balance is settled — same shape as
    :class:`ConflictError` but with a code that lets the client
    render a precise toast.
    """

    def __init__(self, *, message: str | None = None) -> None:
        super().__init__(
            code="BALANCE_NOT_SETTLED",
            http_status=409,
            message=message
            or "Settle the balance with this friend before removing them.",
            details=[
                {
                    "field": "balance",
                    "issue": (
                        "outstanding balance with this friend must be zero"
                    ),
                }
            ],
        )


class ValidationFailedError(AuthError):
    """Manual validation failure (e.g. non-ULID path param) that needs
    the same envelope shape as Pydantic's ``RequestValidationError``."""

    def __init__(self, *, field: str, issue: str) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            http_status=422,
            message="Request failed validation.",
            details=[{"field": field, "issue": issue}],
        )
