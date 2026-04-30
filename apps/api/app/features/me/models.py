"""Pydantic shapes for the ``/v1/me`` endpoints.

Phase 7 ships:
- ``DELETE /v1/me`` — soft account deactivation. No request body, 204 reply.
- ``GET /v1/me/export`` — full self-data dump.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.features.transactions.models import (
    Currency,
    Member,
    Payer,
    SplitMethod,
    TxnType,
)


class MeProfile(BaseModel):
    """Trimmed user profile on the export. Only the fields we own
    server-side; raw email + phone come from Cognito and are not
    re-exposed here."""

    user_id: str
    name: str
    currency: Currency
    status: str
    created_at: datetime


class FriendshipExport(BaseModel):
    """One friendship in the export."""

    friend_user_id: str
    since: datetime


class TransactionExport(BaseModel):
    """One transaction (META + members + payers) in the export."""

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


class ExportResponse(BaseModel):
    """``GET /v1/me/export`` 200 response."""

    profile: MeProfile
    friendships: list[FriendshipExport]
    transactions: list[TransactionExport]
    exported_at: datetime


# ---- Internal config ------------------------------------------------

# How long between user-facing exports. Reuses the Phase 2c rate-limit
# table with a new ``EXPORT_RATE`` row class (one per user).
EXPORT_COOLDOWN_SECONDS: Annotated[int, Field(gt=0)] = 24 * 3600


class DeactivationAck(BaseModel):
    """Internal — not surfaced on the wire (the route returns 204)
    but kept here so test/service code can type-check the
    repository's return.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    deactivated_at: datetime
