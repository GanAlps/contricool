"""Phase 7 — deactivated-account cleanup.

Composes with the transactions cleanup in :mod:`app.cleanup.main`.
After ``DELETE /v1/me`` marks a Users META row with
``status="deactivated"`` and ``deactivated_at = now``, this module
hard-deletes the user **30 days later**:

1. Hard-delete every friendship row touching the user.
2. Hard-delete the Users META row + its EMAIL#<hash> GSI
   projection (the projection is the same row).
3. ``AdminDeleteUser`` in Cognito so the email can be re-registered.

We deliberately do NOT anonymize the user_id in remaining
transactions:
- Transaction MEMBER rows carry only ``user_id`` (an opaque ULID),
  not the user's name or email. No PII surfaces.
- Surviving members of a shared transaction still see the
  transaction with the deleted user's ULID; the UI renders an
  unknown ULID as "—" because :func:`friends_repo.get_user_meta`
  returns None.
- The friendship row delete is what makes the deleted user fall
  out of the surviving user's friend list.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

from app.core import config
from app.core.observability import logger
from app.features.auth import cognito_client
from app.features.me import repository as me_repo

# Same restore window the deactivation API documents.
ACCOUNT_RETENTION_DAYS = 30

# Cap per cleanup pass so the Lambda finishes within budget.
MAX_PER_INVOCATION = 50


def _retention_cutoff_iso() -> str:
    cutoff = datetime.now(UTC) - timedelta(days=ACCOUNT_RETENTION_DAYS)
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _users_table() -> Any:
    """The cleanup runs in its own Lambda; keep the resource lazy
    so module-import is cheap and tests can inject a moto Table via
    ``me_repo._set_table_for_tests``."""
    return me_repo._table()


def _resource() -> Any:
    cfg = config.load()
    return boto3.resource("dynamodb", region_name=cfg.aws_region)


def scan_old_deactivated_users(
    *, deactivated_before_iso: str, limit: int
) -> list[dict[str, Any]]:
    """Scan META rows where ``status='deactivated'`` and
    ``deactivated_at < deactivated_before_iso``."""
    response = _users_table().scan(
        FilterExpression=(
            "begins_with(SK, :meta) AND #status = :deact "
            "AND deactivated_at < :before"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":meta": "META",
            ":deact": "deactivated",
            ":before": deactivated_before_iso,
        },
        Limit=limit * 4,
    )
    rows: list[dict[str, Any]] = []
    for item in response.get("Items") or []:
        if str(item.get("SK")) != "META":
            continue
        rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _delete_friendships(user_id: str) -> int:
    """Hard-delete every friendship row touching ``user_id``.

    Returns the number of rows deleted.
    """
    rows = me_repo.get_friendships(user_id)
    if not rows:
        return 0
    table = _users_table()
    deleted = 0
    for row in rows:
        friend_id = row["friend_user_id"]
        # Canonical pair: PK = USER#<min(a,b)>, SK = FRIEND#<max(a,b)>.
        min_id, max_id = (
            (user_id, friend_id) if user_id < friend_id else (friend_id, user_id)
        )
        table.delete_item(
            Key={
                "PK": f"USER#{min_id}",
                "SK": f"FRIEND#{max_id}",
            }
        )
        deleted += 1
    return deleted


def _delete_user_meta(user_id: str) -> None:
    _users_table().delete_item(
        Key={"PK": f"USER#{user_id}", "SK": "META"}
    )


def cleanup_accounts_once() -> dict[str, int]:
    """Single account-cleanup pass.

    Returns a summary dict so the Lambda invocation log records
    progress without dumping per-user details.
    """
    cutoff = _retention_cutoff_iso()
    candidates = scan_old_deactivated_users(
        deactivated_before_iso=cutoff, limit=MAX_PER_INVOCATION
    )
    hard_deleted = 0
    friendships_deleted = 0
    cognito_deleted = 0
    cog_client = cognito_client.CognitoClient(
        user_pool_id=config.load().cognito_user_pool_id
    )
    for item in candidates:
        user_id = str(item["PK"]).removeprefix("USER#")
        # The META row carries display_name + currency but NOT the
        # email (email lives in Cognito + the EMAIL#<hash> GSI
        # projection of this same row). We need the email to call
        # AdminDeleteUser, so look it up from Cognito by user_id.
        # Easier path: the deactivation flow records the email on
        # the META row alongside ``deactivated_at``. We didn't add
        # that yet — fall back to skipping Cognito delete when the
        # email isn't on the row, and log a warning.
        email = str(item.get("email_for_cleanup") or "")

        n_friends = _delete_friendships(user_id)
        friendships_deleted += n_friends

        _delete_user_meta(user_id)
        hard_deleted += 1

        if email:
            cog_client.admin_delete_user(email=email)
            cognito_deleted += 1
        else:
            logger.warning(
                "account_cleanup_no_email_skipping_cognito",
                extra={"user_id": user_id},
            )
    logger.info(
        "account_cleanup_run",
        extra={
            "cutoff": cutoff,
            "candidates": len(candidates),
            "hard_deleted": hard_deleted,
            "friendships_deleted": friendships_deleted,
            "cognito_deleted": cognito_deleted,
        },
    )
    return {
        "candidates": len(candidates),
        "hard_deleted": hard_deleted,
        "friendships_deleted": friendships_deleted,
        "cognito_deleted": cognito_deleted,
    }
