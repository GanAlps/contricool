"""FastAPI router for ``/v1/transactions/*``.

Routes are thin adaptors around :mod:`app.features.transactions.service`.
All routes are authenticated via the JWT authorizer + the
``current_principal`` dependency (Phase 2c).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, status

from app.core.dependencies import current_principal
from app.core.principal import Principal
from app.features.transactions import service
from app.features.transactions.errors import (
    IdempotencyKeyRequiredError,
    ValidationFailedError,
)
from app.features.transactions.models import (
    CreateTransactionRequest,
    ListTransactionsQuery,
    ListTransactionsResponse,
    Transaction,
)

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
# Accept any reasonable client-supplied idempotency key — UUID v4, ULID,
# or arbitrary 8..128-char ASCII. Stricter validation belongs at the
# client SDK; the server only needs the key to be a usable opaque token.
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def _validate_ulid(name: str, value: str) -> str:
    if not _ULID_RE.fullmatch(value):
        raise ValidationFailedError(
            field=name, issue="must be a 26-character Crockford ULID"
        )
    return value


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Transaction,
)
def create_transaction_route(
    body: CreateTransactionRequest,
    principal: Principal = Depends(current_principal),  # noqa: B008
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Transaction:
    if not idempotency_key:
        raise IdempotencyKeyRequiredError()
    if not _IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        raise ValidationFailedError(
            field="Idempotency-Key", issue="malformed idempotency key"
        )
    return service.create_transaction(
        requester_id=principal.user_id,
        body=body,
        idempotency_key=idempotency_key,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ListTransactionsResponse,
)
def list_transactions_route(
    query: ListTransactionsQuery = Depends(),  # noqa: B008
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> ListTransactionsResponse:
    return service.list_transactions(
        requester_id=principal.user_id,
        limit=query.limit,
        cursor=query.cursor,
        friend_id=query.friend_id,
    )


@router.get(
    "/{txn_id}",
    status_code=status.HTTP_200_OK,
    response_model=Transaction,
)
def get_transaction_route(
    txn_id: str,
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> Transaction:
    txn_id = _validate_ulid("txn_id", txn_id)
    return service.get_transaction(
        requester_id=principal.user_id, txn_id=txn_id
    )
