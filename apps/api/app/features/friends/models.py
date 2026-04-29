"""Pydantic request / response shapes for the friends feature.

The shapes are the single source of truth for both the FastAPI router
(via ``response_model``) and the OpenAPI emit that backs the generated
TypeScript SDK.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Currency = Literal["USD", "INR"]


class AddFriendRequest(BaseModel):
    """Payload for ``POST /v1/friends/add``.

    ``email`` is the only identifier accepted at MVP per CONSTRAINTS.md
    "Friend search/add is by email only at MVP". Phone is unverified-
    metadata-only on Cognito and is never used for lookup.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class FriendItem(BaseModel):
    """One row in the friends list — the friend's identity-safe shape."""

    user_id: str
    name: str
    currency: Currency
    since: datetime


class AddFriendResponse(FriendItem):
    """``POST /v1/friends/add`` 200 response — same shape as a list row."""


class ListFriendsResponse(BaseModel):
    """``GET /v1/friends`` 200 response.

    ``next_cursor`` is opaque (HMAC-signed, requester-bound). When
    ``null`` the caller has reached the end of their friend list.
    """

    items: list[FriendItem]
    next_cursor: str | None = None


# Public limit bounds re-exported for the route Depends() and tests.
MAX_LIMIT = 100
DEFAULT_LIMIT = 50


class ListFriendsQuery(BaseModel):
    """Query-string params for ``GET /v1/friends``."""

    model_config = ConfigDict(extra="forbid")

    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    cursor: str | None = None


SettlementStatus = Literal["settled", "friend_owes", "you_owe"]


class FriendBalanceResponse(BaseModel):
    """``GET /v1/friends/{user_id}/balance`` 200 response.

    Phase 3a returns the fully-typed shape with zeros / ``null`` so
    Phase 3b's UI can render the eventual balance card without
    re-architecting when Phase 4 wires real transaction aggregates.
    """

    user_id: str
    currency: Currency
    net: Decimal
    settlement_status: SettlementStatus
    last_transaction_at: datetime | None = None
