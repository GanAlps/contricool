"""Service layer for the transactions feature.

Owns the per-method invariants (which models.py deliberately doesn't
enforce so we can raise typed errors with stable codes) and orchestrates
the cross-table create flow:

1. Validate the body's per-method invariants → raise typed AuthError.
2. Pre-flight friendship + currency check (one BatchGetItem per).
3. Compute server-side ``owed_amount`` via ``splits.py``.
4. Hand to ``repository.create_transaction`` for the cross-table
   ``TransactWriteItems`` write.
5. Map an ``IdempotencyHit`` to either a cached-replay 201 or a 409
   ``IDEMPOTENCY_KEY_REUSED`` based on the stored request hash.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.observability import logger
from app.features.transactions import balance, splits
from app.features.transactions import repository as repo
from app.features.transactions.errors import (
    CurrencyMismatchError,
    IdempotencyKeyReusedError,
    InvalidCursorError,
    InvalidDateError,
    MemberCountError,
    NotFoundError,
    NotFriendError,
    OwedSumError,
    PaidSumError,
    PayerNotMemberError,
    PercentSumError,
    SelfNotMemberError,
    ValidationFailedError,
)
from app.features.transactions.models import (
    DATE_FUTURE_TOLERANCE_DAYS,
    DATE_PAST_HORIZON_DAYS,
    MAX_MEMBERS,
    MIN_MEMBERS,
    PERCENT_TOLERANCE,
    SUM_TOLERANCE,
    CreateTransactionRequest,
    ListTransactionsResponse,
    Member,
    Payer,
    SettlementStatus,
    Transaction,
    TransactionListItem,
)

# ---- Cursor (reuse the friends/cursor module shape) ----------------


def _cursor_encode(*, requester_id: str, last_gsi1sk: str) -> str:
    from app.features.friends import cursor as friends_cursor

    # The friends cursor module's ``encode`` is requester-bound + HMAC;
    # we just feed the last-seen GSI1SK as the "last" anchor.
    return friends_cursor.encode(
        requester_id=requester_id, last_friend_id=last_gsi1sk
    )


def _cursor_decode(*, cursor: str, requester_id: str) -> str:
    from app.features.friends import cursor as friends_cursor

    try:
        return friends_cursor.decode(cursor=cursor, requester_id=requester_id)
    except friends_cursor.InvalidCursorError as exc:
        raise InvalidCursorError() from exc


# ---- Per-method invariant checks (typed errors) --------------------


def validate_create_payload(
    *, requester_id: str, body: CreateTransactionRequest
) -> None:
    """Raise the right typed AuthError for per-method invariants.

    Pydantic guarantees structural shape (types + ranges + uniqueness).
    Here we enforce the cross-field rules.
    """
    # Date window check.
    from datetime import date as _date
    from datetime import timedelta

    today = datetime.now(UTC).date()
    if body.txn_date > today + timedelta(days=DATE_FUTURE_TOLERANCE_DAYS):
        raise InvalidDateError(
            message="Transaction date is too far in the future."
        )
    if body.txn_date < today - timedelta(days=DATE_PAST_HORIZON_DAYS):
        raise InvalidDateError(
            message="Transaction date is too far in the past."
        )
    _ = _date  # silence ruff if unused

    n = len(body.members)
    if n < MIN_MEMBERS:
        raise MemberCountError(
            code="MIN_MEMBERS",
            message=f"At least {MIN_MEMBERS} members required.",
        )
    if n > MAX_MEMBERS:  # pragma: no cover - Pydantic enforces upstream
        raise MemberCountError(
            code="MAX_MEMBERS",
            message=f"At most {MAX_MEMBERS} members allowed.",
        )
    member_ids = [m.user_id for m in body.members]
    if len(set(member_ids)) != n:
        raise ValidationFailedError(
            field="members", issue="member user_ids must be unique"
        )
    if requester_id not in member_ids:
        raise SelfNotMemberError()

    # Payer rules.
    payer_ids = [p.user_id for p in body.payers]
    if len(set(payer_ids)) != len(payer_ids):
        raise ValidationFailedError(
            field="payers", issue="payer user_ids must be unique"
        )
    member_id_set = set(member_ids)
    for p in body.payers:
        if p.user_id not in member_id_set:
            raise PayerNotMemberError()
    paid_sum = sum((p.paid_amount for p in body.payers), Decimal("0"))
    if abs(paid_sum - body.amount) > SUM_TOLERANCE:
        raise PaidSumError()

    # Per-method rules.
    if body.split_method == "amount":
        owed_total = Decimal("0")
        for m in body.members:
            if m.owed_amount is None:
                raise ValidationFailedError(
                    field="members",
                    issue="owed_amount required for split_method='amount'",
                )
            owed_total += m.owed_amount
        if abs(owed_total - body.amount) > SUM_TOLERANCE:
            raise OwedSumError()
    elif body.split_method == "share":
        for m in body.members:
            if m.share is None or m.share <= 0:
                raise ValidationFailedError(
                    field="members",
                    issue="positive share required for split_method='share'",
                )
    elif body.split_method == "percent":
        percent_total = Decimal("0")
        for m in body.members:
            if m.percent is None or m.percent <= 0:
                raise ValidationFailedError(
                    field="members",
                    issue="positive percent required for split_method='percent'",
                )
            percent_total += m.percent
        if abs(percent_total - Decimal("100")) > PERCENT_TOLERANCE:
            raise PercentSumError()

    # Settlement special case.
    if body.type == "settlement":
        if n != 2:
            raise MemberCountError(
                code="SETTLEMENT_SHAPE",
                message="Settlement must have exactly 2 members.",
            )
        if len(body.payers) != 1:
            raise ValidationFailedError(
                field="payers", issue="settlement must have exactly 1 payer"
            )
        if body.split_method != "amount":
            raise ValidationFailedError(
                field="split_method",
                issue="settlement requires split_method='amount'",
            )
        payer_id = body.payers[0].user_id
        for m in body.members:
            expected = Decimal("0") if m.user_id == payer_id else body.amount
            if m.owed_amount is None or m.owed_amount.compare(expected) != 0:
                raise OwedSumError()


# ---- Hashing the body for idempotency replay -----------------------


def request_hash(body: CreateTransactionRequest) -> str:
    """Stable hash of the request body for idempotency-replay
    discrimination. We dump via Pydantic's deterministic JSON output
    and SHA-256 the bytes."""
    payload = body.model_dump_json(by_alias=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---- Create ---------------------------------------------------------


def _compute_owed_amounts(body: CreateTransactionRequest) -> list[Decimal]:
    """Compute server-side ``owed_amount`` per member."""
    if body.type == "settlement":
        # Validation has guaranteed exactly 1 payer + 2 members.
        payer_id = body.payers[0].user_id
        idx = next(
            i for i, m in enumerate(body.members) if m.user_id == payer_id
        )
        return splits.settlement_owed_amounts(
            amount=body.amount, payer_index=idx
        )
    if body.split_method == "amount":
        return splits.compute_owed_amounts(
            method="amount",
            amount=body.amount,
            owed_inputs=[
                m.owed_amount or Decimal("0") for m in body.members
            ],
        )
    if body.split_method == "equal":
        return splits.compute_owed_amounts(
            method="equal",
            amount=body.amount,
            member_count=len(body.members),
        )
    if body.split_method == "share":
        return splits.compute_owed_amounts(
            method="share",
            amount=body.amount,
            shares=[m.share or Decimal("0") for m in body.members],
        )
    return splits.compute_owed_amounts(
        method="percent",
        amount=body.amount,
        percents=[m.percent or Decimal("0") for m in body.members],
    )


def _to_response(
    *,
    txn_id: str,
    body: CreateTransactionRequest,
    creator_id: str,
    owed_amounts: list[Decimal],
    created_at: datetime,
    updated_at: datetime,
) -> Transaction:
    members: list[Member] = []
    for m, owed in zip(body.members, owed_amounts, strict=True):
        members.append(
            Member(
                user_id=m.user_id,
                owed_amount=owed,
                share=m.share,
                percent=m.percent,
            )
        )
    payers = [
        Payer(user_id=p.user_id, paid_amount=p.paid_amount)
        for p in body.payers
    ]
    return Transaction(
        txn_id=txn_id,
        creator_id=creator_id,
        name=body.name,
        type=body.type,
        amount=body.amount,
        currency=body.currency,
        txn_date=body.txn_date,
        note=body.note,
        split_method=body.split_method,
        members=members,
        payers=payers,
        created_at=created_at,
        updated_at=updated_at,
    )


def create_transaction(
    *,
    requester_id: str,
    body: CreateTransactionRequest,
    idempotency_key: str,
) -> Transaction:
    """Validate + persist a transaction. Idempotent on
    ``(requester_id, idempotency_key)``."""
    validate_create_payload(requester_id=requester_id, body=body)

    other_member_ids = [
        m.user_id for m in body.members if m.user_id != requester_id
    ]

    # Currency check: every other-member must share the txn's currency.
    currencies = repo.get_user_currencies([requester_id, *other_member_ids])
    for uid in [requester_id, *other_member_ids]:
        if currencies.get(uid) != body.currency:
            logger.info(
                "txn_create_currency_mismatch",
                extra={"creator_id": requester_id, "currency": body.currency},
            )
            raise CurrencyMismatchError()

    # Friendship pre-flight (cheap UX win; the transact's
    # ConditionCheck is the authoritative gate at write time).
    friend_ids = repo.get_friendship_ids(requester_id, other_member_ids)
    missing = [uid for uid in other_member_ids if uid not in friend_ids]
    if missing:
        logger.info(
            "txn_create_not_friend",
            extra={"creator_id": requester_id, "missing_count": len(missing)},
        )
        raise NotFriendError()

    owed_amounts = _compute_owed_amounts(body)

    members_payload = [
        {
            "user_id": m.user_id,
            "owed_amount": owed,
            "share": m.share,
            "percent": m.percent,
        }
        for m, owed in zip(body.members, owed_amounts, strict=True)
    ]
    payers_payload = [
        {"user_id": p.user_id, "paid_amount": p.paid_amount}
        for p in body.payers
    ]

    body_hash = request_hash(body)

    def _payload_factory(
        txn_id: str, created_at: datetime, updated_at: datetime
    ) -> dict[str, Any]:
        # Built once during the transact write — the cached payload
        # uses the same ``txn_id`` and ``created_at`` the META row
        # commits with, so an idempotent replay returns the real
        # txn_id rather than a service-side placeholder.
        return _to_response(
            txn_id=txn_id,
            body=body,
            creator_id=requester_id,
            owed_amounts=owed_amounts,
            created_at=created_at,
            updated_at=updated_at,
        ).model_dump(mode="json")

    inputs = repo.CreateInputs(
        creator_id=requester_id,
        name=body.name,
        type=body.type,
        amount=body.amount,
        currency=body.currency,
        txn_date=body.txn_date.isoformat(),
        note=body.note,
        split_method=body.split_method,
        members=members_payload,
        payers=payers_payload,
    )
    result = repo.create_transaction(
        inputs=inputs,
        idempotency_key=idempotency_key,
        request_hash=body_hash,
        response_payload_factory=_payload_factory,
    )

    if isinstance(result, repo.IdempotencyHit):
        cached_hash = str(result.record.get("request_hash") or "")
        if cached_hash != body_hash:
            logger.info(
                "txn_create_idempotency_reused",
                extra={
                    "creator_id": requester_id,
                    "key_suffix": idempotency_key[-8:],
                },
            )
            raise IdempotencyKeyReusedError()
        cached_response = json.loads(str(result.record.get("response") or "{}"))
        logger.info(
            "txn_create_idempotency_replay",
            extra={
                "creator_id": requester_id,
                "key_suffix": idempotency_key[-8:],
            },
        )
        return Transaction.model_validate(cached_response)

    # Successful first-time create — re-serialise with the actual ids/timestamps.
    response = _to_response(
        txn_id=result.txn_id,
        body=body,
        creator_id=requester_id,
        owed_amounts=owed_amounts,
        created_at=result.created_at,
        updated_at=result.updated_at,
    )
    logger.info(
        "txn_created",
        extra={
            "creator_id": requester_id,
            "txn_id": result.txn_id,
            "type": body.type,
            "split_method": body.split_method,
            "member_count": len(body.members),
        },
    )
    return response


# ---- Get ------------------------------------------------------------


def get_transaction(*, requester_id: str, txn_id: str) -> Transaction:
    meta = repo.get_meta(txn_id)
    if meta is None or meta.deleted_at is not None:
        raise NotFoundError()
    if requester_id not in meta.member_ids:
        raise NotFoundError()
    members_rows = repo.get_members(txn_id)
    members = [
        Member(
            user_id=mr.user_id,
            owed_amount=mr.owed_amount,
            share=mr.share,
            percent=mr.percent,
        )
        for mr in members_rows
    ]
    payers = [
        Payer(
            user_id=str(p["user_id"]),
            paid_amount=Decimal(str(p["paid_amount"])),
        )
        for p in meta.payers
    ]
    created_at = datetime.fromisoformat(meta.created_at.replace("Z", "+00:00"))
    updated_at = datetime.fromisoformat(meta.updated_at.replace("Z", "+00:00"))
    deleted_at = (
        datetime.fromisoformat(meta.deleted_at.replace("Z", "+00:00"))
        if meta.deleted_at
        else None
    )
    from datetime import date as _date

    return Transaction(
        txn_id=meta.txn_id,
        creator_id=meta.creator_id,
        name=meta.name,
        type=meta.type,  # type: ignore[arg-type]
        amount=meta.amount,
        currency=meta.currency,  # type: ignore[arg-type]
        txn_date=_date.fromisoformat(meta.txn_date),
        note=meta.note,
        split_method=meta.split_method,  # type: ignore[arg-type]
        members=members,
        payers=payers,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


# ---- List ----------------------------------------------------------


def list_transactions(
    *,
    requester_id: str,
    limit: int,
    cursor: str | None,
    friend_id: str | None,
) -> ListTransactionsResponse:
    last_gsi1sk: str | None = None
    if cursor:
        last_gsi1sk = _cursor_decode(cursor=cursor, requester_id=requester_id)

    over_fetch = limit * (2 if friend_id else 1)
    my_rows, _ = repo.query_user_member_rows(
        requester_id, limit=over_fetch + 1, last_gsi1_sk=last_gsi1sk
    )
    if friend_id and friend_id != requester_id:
        fr_rows, _ = repo.query_user_member_rows(
            friend_id, limit=over_fetch + 1, last_gsi1_sk=None
        )
        friend_txn_ids = {tid for tid, _ in fr_rows}
        intersected = [(t, sk) for (t, sk) in my_rows if t in friend_txn_ids]
    else:
        intersected = my_rows

    page = intersected[:limit]
    has_more = len(intersected) > limit

    next_cursor: str | None = None
    if has_more and page:
        next_cursor = _cursor_encode(
            requester_id=requester_id, last_gsi1sk=page[-1][1]
        )

    txn_ids = [tid for tid, _ in page]
    metas = repo.batch_get_metas(txn_ids)

    items: list[TransactionListItem] = []
    # Need each txn's members to get my_owed_amount.
    for tid, _gsi1sk in page:
        meta = metas.get(tid)
        if meta is None or meta.deleted_at is not None:
            continue
        if requester_id not in meta.member_ids:
            continue
        member_rows = repo.get_members(tid)
        my_owed = next(
            (mr.owed_amount for mr in member_rows if mr.user_id == requester_id),
            Decimal("0.00"),
        )
        from datetime import date as _date

        items.append(
            TransactionListItem(
                txn_id=meta.txn_id,
                name=meta.name,
                type=meta.type,  # type: ignore[arg-type]
                amount=meta.amount,
                currency=meta.currency,  # type: ignore[arg-type]
                txn_date=_date.fromisoformat(meta.txn_date),
                split_method=meta.split_method,  # type: ignore[arg-type]
                creator_id=meta.creator_id,
                my_owed_amount=my_owed,
                created_at=datetime.fromisoformat(
                    meta.created_at.replace("Z", "+00:00")
                ),
            )
        )
    return ListTransactionsResponse(items=items, next_cursor=next_cursor)


# ---- Balance -------------------------------------------------------


def compute_pair_balance(
    *, requester_id: str, friend_id: str
) -> tuple[Decimal, SettlementStatus, datetime | None]:
    """Compute the requester's balance with ``friend_id`` from their
    transactions. Skips soft-deleted transactions.
    """
    # Fetch all of requester's MEMBER rows; for each, check if friend
    # is also a member; if so, hydrate META + members and compute.
    my_rows, _ = repo.query_user_member_rows(
        requester_id, limit=500, last_gsi1_sk=None
    )
    fr_rows, _ = repo.query_user_member_rows(
        friend_id, limit=500, last_gsi1_sk=None
    )
    fr_ids = {tid for tid, _ in fr_rows}
    intersected = [tid for (tid, _) in my_rows if tid in fr_ids]

    metas = repo.batch_get_metas(intersected)

    summaries: list[balance.TxnSummary] = []
    for tid in intersected:
        meta = metas.get(tid)
        if meta is None or meta.deleted_at is not None:
            continue
        member_rows = repo.get_members(tid)
        members_map: dict[str, Decimal] = {
            mr.user_id: mr.owed_amount for mr in member_rows
        }
        payers = [
            (str(p["user_id"]), Decimal(str(p["paid_amount"])))
            for p in meta.payers
        ]
        created_at = datetime.fromisoformat(
            meta.created_at.replace("Z", "+00:00")
        )
        summaries.append(
            balance.TxnSummary(
                txn_id=meta.txn_id,
                amount=meta.amount,
                payers=payers,
                members=members_map,
                txn_date=meta.txn_date,
                created_at=created_at,
            )
        )

    result = balance.compute_pair_balance(
        my_id=requester_id, friend_id=friend_id, txns=summaries
    )
    return result.net, result.settlement_status, result.last_transaction_at
