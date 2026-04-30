"""Service layer for the ``me`` feature.

Composes:
- ``DELETE /v1/me`` → repo deactivate + Cognito disable + Cognito
  global-sign-out, all idempotent.
- ``GET /v1/me/export`` → friendships + transactions list +
  per-transaction META + members.
"""
from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as _date
from decimal import Decimal

from app.core import config
from app.core.observability import logger
from app.features.auth import cognito_client
from app.features.auth.errors import AuthError
from app.features.friends import repository as friends_repo
from app.features.me import repository as me_repo
from app.features.me.models import (
    EXPORT_COOLDOWN_SECONDS,
    ExportResponse,
    FriendshipExport,
    MeProfile,
    TransactionExport,
)
from app.features.transactions import repository as txn_repo
from app.features.transactions.models import Member, Payer


class ExportRateLimitedError(AuthError):
    """The requester exported their data within the cooldown window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            code="RATE_LIMITED",
            http_status=429,
            message="Export is rate-limited; try again later.",
            retry_after_seconds=retry_after,
        )


# ---- Delete -----------------------------------------------------------


def delete_my_account(*, requester_id: str, requester_email: str) -> None:
    """Soft-deactivate the requester.

    Idempotent: a second call returns success with no extra DDB write.
    """
    result = me_repo.deactivate_user(requester_id)
    # Cognito ops are idempotent on the server side. Run them
    # regardless of ``already_deactivated`` so a half-applied prior
    # call (e.g. DDB write succeeded but Cognito disable failed) is
    # eventually consistent.
    cog = cognito_client.CognitoClient(
        user_pool_id=config.load().cognito_user_pool_id
    )
    cog.admin_disable_user(email=requester_email)
    cog.admin_user_global_sign_out(email=requester_email)
    logger.info(
        "me_deactivated",
        extra={
            "user_id": requester_id,
            "deactivated_at": result.deactivated_at.isoformat(),
            "already_deactivated": result.already_deactivated,
        },
    )


# ---- Export -----------------------------------------------------------


def export_my_data(*, requester_id: str) -> ExportResponse:
    """Build a JSON dump of the requester's data.

    Rate-limited to 1 export per ``EXPORT_COOLDOWN_SECONDS``.
    """
    try:
        me_repo.consume_export_quota(
            user_id=requester_id, cooldown_seconds=EXPORT_COOLDOWN_SECONDS
        )
    except me_repo.ExportTooSoonError as exc:
        raise ExportRateLimitedError(retry_after=exc.retry_after) from exc

    profile_meta = friends_repo.get_user_meta(requester_id)
    if profile_meta is None:
        raise AuthError(
            code="NOT_FOUND",
            http_status=404,
            message="No such user.",
        )
    # The status field is on the META row directly; reuse the existing
    # repo's lower-level reader.
    raw_meta = friends_repo._table().get_item(
        Key={"PK": f"USER#{requester_id}", "SK": "META"},
    ).get("Item") or {}
    status = str(raw_meta.get("status") or "active")
    created_at_iso = str(raw_meta.get("created_at") or "")
    created_at = (
        datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        if created_at_iso
        else datetime.now(UTC)
    )

    friendships_raw = me_repo.get_friendships(requester_id)
    friendships = [
        FriendshipExport(
            friend_user_id=f["friend_user_id"],
            since=datetime.fromisoformat(
                str(f["since"]).replace("Z", "+00:00")
            ),
        )
        for f in friendships_raw
    ]

    # Transactions: list every TXN where the user is a member.
    txn_rows, _ = txn_repo.query_user_member_rows(
        requester_id, limit=500, last_gsi1_sk=None
    )
    txn_ids = [tid for tid, _ in txn_rows]
    metas = txn_repo.batch_get_metas(txn_ids)

    transactions: list[TransactionExport] = []
    for tid in txn_ids:
        meta = metas.get(tid)
        if meta is None:  # pragma: no cover - defensive: batch_get can lose a key under heavy churn
            continue
        member_rows = txn_repo.get_members(tid)
        transactions.append(
            TransactionExport(
                txn_id=meta.txn_id,
                creator_id=meta.creator_id,
                name=meta.name,
                type=meta.type,  # type: ignore[arg-type]
                amount=meta.amount,
                currency=meta.currency,  # type: ignore[arg-type]
                txn_date=_date.fromisoformat(meta.txn_date),
                note=meta.note,
                split_method=meta.split_method,  # type: ignore[arg-type]
                members=[
                    Member(
                        user_id=mr.user_id,
                        owed_amount=mr.owed_amount,
                        share=mr.share,
                        percent=mr.percent,
                    )
                    for mr in member_rows
                ],
                payers=[
                    Payer(
                        user_id=str(p["user_id"]),
                        paid_amount=Decimal(str(p["paid_amount"])),
                    )
                    for p in meta.payers
                ],
                created_at=datetime.fromisoformat(
                    meta.created_at.replace("Z", "+00:00")
                ),
                updated_at=datetime.fromisoformat(
                    meta.updated_at.replace("Z", "+00:00")
                ),
                deleted_at=(
                    datetime.fromisoformat(
                        meta.deleted_at.replace("Z", "+00:00")
                    )
                    if meta.deleted_at
                    else None
                ),
            )
        )

    response = ExportResponse(
        profile=MeProfile(
            user_id=requester_id,
            name=profile_meta.name,
            currency=profile_meta.currency,  # type: ignore[arg-type]
            status=status,
            created_at=created_at,
        ),
        friendships=friendships,
        transactions=transactions,
        exported_at=datetime.now(UTC),
    )
    logger.info(
        "me_exported",
        extra={
            "user_id": requester_id,
            "friendship_count": len(friendships),
            "transaction_count": len(transactions),
        },
    )
    return response
