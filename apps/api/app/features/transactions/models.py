"""Pydantic v2 schemas for the transactions feature.

The schemas are the single source of truth for both the FastAPI router
(via ``response_model``) and the OpenAPI emit that backs the generated
TypeScript SDK in ``packages/client-sdk``.

Pydantic only enforces *structural* validation here — types, regex,
length / range bounds. The richer per-split-method invariants
(percent sums to 100, payers ⊆ members, owed sums match amount,
settlement shape) live in :mod:`app.features.transactions.service`
because they need to raise typed application errors with stable codes
(``OWED_SUM``, ``PERCENT_SUM``, ``PAYER_NOT_MEMBER`` …) that the
client UX depends on. Raising those from inside Pydantic validators
collapses them into a single 422 ``VALIDATION_ERROR``.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Currency = Literal["USD", "INR"]
SplitMethod = Literal["equal", "amount", "share", "percent"]
TxnType = Literal["expense", "settlement"]
SettlementStatus = Literal["settled", "friend_owes", "you_owe"]

# Crockford-base32 ULID; same regex used in the friends feature.
_ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"

# Domain bounds.
MIN_MEMBERS = 2
MAX_MEMBERS = 10
NAME_MAX = 120
NOTE_MAX = 500
DATE_FUTURE_TOLERANCE_DAYS = 1
DATE_PAST_HORIZON_DAYS = 365 * 10
PERCENT_TOLERANCE = Decimal("0.01")
SUM_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class MemberInput(BaseModel):
    """One member entry on a create request."""

    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[str, Field(pattern=_ULID_PATTERN, min_length=26, max_length=26)]
    share: (
        Annotated[
            Decimal,
            Field(gt=0, max_digits=12, decimal_places=4),
        ]
        | None
    ) = None
    percent: (
        Annotated[
            Decimal,
            Field(ge=0, le=100, max_digits=5, decimal_places=2),
        ]
        | None
    ) = None
    owed_amount: (
        Annotated[
            Decimal,
            Field(ge=0, max_digits=12, decimal_places=2),
        ]
        | None
    ) = None


class PayerInput(BaseModel):
    """One payer entry on a create request."""

    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[str, Field(pattern=_ULID_PATTERN, min_length=26, max_length=26)]
    paid_amount: Annotated[
        Decimal, Field(gt=0, max_digits=12, decimal_places=2)
    ]


class CreateTransactionRequest(BaseModel):
    """``POST /v1/transactions`` request body.

    Structural validation only here — per-method invariants are in
    :func:`app.features.transactions.service.validate_create_payload`.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=NAME_MAX, strip_whitespace=True),
    ]
    type: TxnType
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    currency: Currency
    txn_date: date
    note: Annotated[
        str, StringConstraints(max_length=NOTE_MAX, strip_whitespace=False)
    ] = ""
    split_method: SplitMethod
    # Pydantic surfaces ``min_length=2`` to the generated OpenAPI as
    # ``minItems: 2`` so SDK consumers see the real domain minimum.
    # Note: ``service.validate_create_payload`` keeps an equivalent
    # ``MIN_MEMBERS`` check as defensive — the typed
    # ``MemberCountError(code=MIN_MEMBERS)`` returns a stable error
    # code if the validate path is ever called outside the route.
    members: Annotated[list[MemberInput], Field(min_length=MIN_MEMBERS, max_length=MAX_MEMBERS)]
    payers: Annotated[list[PayerInput], Field(min_length=1, max_length=MAX_MEMBERS)]


# ---------------------------------------------------------------------------
# Outputs (response shapes)
# ---------------------------------------------------------------------------


class Member(BaseModel):
    """One member, with the server-computed ``owed_amount``."""

    user_id: str
    owed_amount: Decimal
    share: Decimal | None = None
    percent: Decimal | None = None


class Payer(BaseModel):
    user_id: str
    paid_amount: Decimal


class Transaction(BaseModel):
    """``POST /v1/transactions`` 201 + ``GET /v1/transactions/{id}`` 200."""

    txn_id: str
    creator_id: str
    name: str
    type: TxnType
    amount: Decimal
    currency: Currency
    txn_date: date
    note: str
    split_method: SplitMethod
    members: list[Member]
    payers: list[Payer]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TransactionListItem(BaseModel):
    """One row in ``GET /v1/transactions`` — META + the requester's
    owed/paid amounts.

    Both ``my_owed_amount`` and ``my_paid_amount`` are surfaced so the
    dashboard summary can compute ``net = paid - owed`` per transaction
    without an extra round-trip to read META payers. ``my_paid_amount``
    is the requester's slot in ``meta.payers`` (0.00 if they didn't pay).

    ``payer_user_ids`` lists every payer's user_id (deduplicated, in the
    server-canonical order from ``meta.payers``) so the client can
    render "Paid by <name>" / "Paid by Multiple" without a follow-up
    GET on each row. We surface user_ids only — name resolution
    happens client-side via the cached friend list + the auth user, so
    no extra backend call or PII surface beyond what the friend list
    already exposes.
    """

    txn_id: str
    name: str
    type: TxnType
    amount: Decimal
    currency: Currency
    txn_date: date
    split_method: SplitMethod
    creator_id: str
    my_owed_amount: Decimal
    my_paid_amount: Decimal
    payer_user_ids: list[str]
    created_at: datetime


MAX_LIST_LIMIT = 100
DEFAULT_LIST_LIMIT = 20


class ListTransactionsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: Annotated[int, Field(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT
    cursor: str | None = None
    friend_id: (
        Annotated[
            str, Field(pattern=_ULID_PATTERN, min_length=26, max_length=26)
        ]
        | None
    ) = None


class ListTransactionsResponse(BaseModel):
    items: list[TransactionListItem]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


CommentKind = Literal["user", "system"]
COMMENT_BODY_MAX = 1000
COMMENT_LIST_DEFAULT = 50
COMMENT_LIST_MAX = 100


class CreateCommentRequest(BaseModel):
    """``POST /v1/transactions/{txn_id}/comments`` request body."""

    model_config = ConfigDict(extra="forbid")

    body: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=COMMENT_BODY_MAX,
            strip_whitespace=False,
        ),
    ]


class Comment(BaseModel):
    """One COMMENT row, rendered for the wire."""

    comment_id: str
    txn_id: str
    author_id: str
    body: str
    kind: CommentKind
    created_at: datetime


class ListCommentsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: Annotated[int, Field(ge=1, le=COMMENT_LIST_MAX)] = COMMENT_LIST_DEFAULT
    cursor: str | None = None


class ListCommentsResponse(BaseModel):
    """``GET /v1/transactions/{txn_id}/comments`` 200 body."""

    items: list[Comment]
    next_cursor: str | None = None


__all__ = [
    "COMMENT_BODY_MAX",
    "COMMENT_LIST_DEFAULT",
    "COMMENT_LIST_MAX",
    "DATE_FUTURE_TOLERANCE_DAYS",
    "DATE_PAST_HORIZON_DAYS",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "MAX_MEMBERS",
    "MIN_MEMBERS",
    "PERCENT_TOLERANCE",
    "SUM_TOLERANCE",
    "Comment",
    "CommentKind",
    "CreateCommentRequest",
    "CreateTransactionRequest",
    "Currency",
    "ListCommentsQuery",
    "ListCommentsResponse",
    "ListTransactionsQuery",
    "ListTransactionsResponse",
    "Member",
    "MemberInput",
    "Payer",
    "PayerInput",
    "SettlementStatus",
    "SplitMethod",
    "Transaction",
    "TransactionListItem",
    "TxnType",
]
