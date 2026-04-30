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
    EXPORT_TRANSACTION_LIMIT,
    ExportResponse,
    FriendshipExport,
    MeProfile,
    MeProfileSlim,
    TransactionExport,
    UpdateProfileRequest,
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


# ---- Update profile ---------------------------------------------------


def update_my_profile(
    *, requester_id: str, body: UpdateProfileRequest
) -> MeProfileSlim:
    """Update the requester's display name on their META row.

    Email and currency are not editable through this surface. A blank
    name (after trim) raises 422 ``VALIDATION_ERROR``. A missing /
    deactivated META row raises 403 ``NOT_ALLOWED``.
    """
    try:
        new_name = me_repo.update_user_name(user_id=requester_id, name=body.name)
    except me_repo.ProfileNameBlankError as exc:
        raise AuthError(
            code="VALIDATION_ERROR",
            http_status=422,
            message="name must not be blank.",
            details=[{"field": "name", "issue": "must not be blank"}],
        ) from exc
    except me_repo.ProfileNotEditableError as exc:
        raise AuthError(
            code="NOT_ALLOWED",
            http_status=403,
            message="Profile cannot be edited for this account.",
        ) from exc

    profile_meta = friends_repo.get_user_meta(requester_id)
    # pragma: no cover - defensive: META vanished after a successful update
    if profile_meta is None:  # pragma: no cover
        raise AuthError(
            code="NOT_FOUND",
            http_status=404,
            message="No such user.",
        )
    logger.info(
        "me_profile_updated", extra={"user_id": requester_id}
    )
    return MeProfileSlim(
        user_id=requester_id,
        name=new_name,
        currency=profile_meta.currency,  # type: ignore[arg-type]
    )


# ---- Delete -----------------------------------------------------------


def delete_my_account(*, requester_id: str, requester_email: str) -> None:
    """Soft-deactivate the requester.

    Idempotent: a second call returns success with no extra DDB write.
    """
    result = me_repo.deactivate_user(requester_id, email=requester_email)
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

    Rate-limited to 1 export per ``EXPORT_COOLDOWN_SECONDS``. The
    user-existence check happens first so a forged token for a
    non-existent user does not burn the rate-limit slot of an
    unrelated DDB key (and so the caller gets the more informative
    404 rather than 429-then-404 across two calls).
    """
    profile_meta = friends_repo.get_user_meta(requester_id)
    if profile_meta is None:
        raise AuthError(
            code="NOT_FOUND",
            http_status=404,
            message="No such user.",
        )

    try:
        me_repo.consume_export_quota(
            user_id=requester_id, cooldown_seconds=EXPORT_COOLDOWN_SECONDS
        )
    except me_repo.ExportTooSoonError as exc:
        raise ExportRateLimitedError(retry_after=exc.retry_after) from exc
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

    # Transactions: list every TXN where the user is a member, up
    # to ``EXPORT_TRANSACTION_LIMIT``. The cap is disclosed in the
    # privacy policy.
    txn_rows, _ = txn_repo.query_user_member_rows(
        requester_id, limit=EXPORT_TRANSACTION_LIMIT, last_gsi1_sk=None
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
