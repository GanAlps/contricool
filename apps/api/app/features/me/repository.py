"""DDB ops for the ``me`` feature.

- Deactivation marks the META row with ``status="deactivated"`` and
  ``deactivated_at``. Idempotent.
- Export reads META + every friendship row + every transaction the
  user is a member of (via the existing transactions repo).
- Export rate-limit is a new row class on ``ContriCool-Users-<env>``::

    PK = USER#<user_id>
    SK = EXPORT_RATE
    last_at = <iso ts>
    ttl = <last_at + 30d>
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import boto3
from botocore.exceptions import ClientError

from app.core import config

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


_default_table: Any | None = None


def _table() -> Table:
    global _default_table
    if _default_table is None:  # pragma: no cover - production cold-start
        cfg = config.load()
        _default_table = boto3.resource(
            "dynamodb", region_name=cfg.aws_region
        ).Table(cfg.users_table_name)
    return cast("Table", _default_table)


def _set_table_for_tests(table: Table | None) -> None:
    """Inject a moto-backed Table for tests; pass ``None`` to clear."""
    global _default_table
    _default_table = table


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---- Deactivation ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeactivationResult:
    user_id: str
    deactivated_at: datetime
    already_deactivated: bool


def deactivate_user(user_id: str, *, email: str) -> DeactivationResult:
    """Set ``status=deactivated`` + ``deactivated_at`` on the META row.

    Also records ``email_for_cleanup`` so the daily cleanup Lambda
    can call ``cognito-idp:AdminDeleteUser`` 30 days later without
    needing to re-derive the email from Cognito (which would
    require an extra IAM action).

    Idempotent — if the row is already deactivated, returns the
    prior timestamp with ``already_deactivated=True``.
    """
    now = _now()
    iso = _iso(now)
    try:
        response = _table().update_item(
            Key={"PK": f"USER#{user_id}", "SK": "META"},
            UpdateExpression=(
                "SET #status = :deact, deactivated_at = :now, "
                "updated_at = :now, email_for_cleanup = :email"
            ),
            ConditionExpression=(
                "attribute_exists(PK) AND #status <> :deact"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":deact": "deactivated",
                ":now": iso,
                ":email": email,
            },
            ReturnValues="ALL_NEW",
        )
        item = response.get("Attributes") or {}
        return DeactivationResult(
            user_id=user_id,
            deactivated_at=datetime.fromisoformat(
                str(item["deactivated_at"]).replace("Z", "+00:00")
            ),
            already_deactivated=False,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ConditionalCheckFailedException":  # pragma: no cover - defensive
            raise
        # Already deactivated — read the prior timestamp.
        item = _table().get_item(
            Key={"PK": f"USER#{user_id}", "SK": "META"},
            ProjectionExpression="deactivated_at",
        ).get("Item") or {}
        prior_iso = str(item.get("deactivated_at") or "")
        if not prior_iso:  # pragma: no cover - defensive: CCFE without row
            raise
        return DeactivationResult(
            user_id=user_id,
            deactivated_at=datetime.fromisoformat(
                prior_iso.replace("Z", "+00:00")
            ),
            already_deactivated=True,
        )


# ---- Export rate-limit ---------------------------------------------


_EXPORT_TTL_SECONDS = 30 * 86400  # generous; the row is informational


class ExportTooSoonError(Exception):
    """Raised by :func:`consume_export_quota` when the user requested
    an export within the cooldown window. Carries ``retry_after`` (s)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("export rate limit hit")
        self.retry_after = retry_after


def consume_export_quota(*, user_id: str, cooldown_seconds: int) -> None:
    """Atomically consume one export slot for ``user_id``.

    Implements a single-row sliding window: writes the new ``last_at``
    only if the prior ``last_at`` is older than ``cooldown_seconds``.
    Raises :class:`ExportTooSoonError` otherwise.
    """
    now = _now()
    now_iso = _iso(now)
    expires_at = int(now.timestamp()) + _EXPORT_TTL_SECONDS
    window_start_iso = _iso(now - _timedelta_seconds(cooldown_seconds))

    try:
        _table().update_item(
            Key={"PK": f"USER#{user_id}", "SK": "EXPORT_RATE"},
            UpdateExpression="SET last_at = :now, #ttl = :ttl",
            ConditionExpression=(
                "attribute_not_exists(last_at) OR last_at < :window_start"
            ),
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":now": now_iso,
                ":ttl": expires_at,
                ":window_start": window_start_iso,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ConditionalCheckFailedException":  # pragma: no cover - defensive
            raise
        # Read prior last_at to compute retry_after.
        item = _table().get_item(
            Key={"PK": f"USER#{user_id}", "SK": "EXPORT_RATE"},
            ProjectionExpression="last_at",
        ).get("Item") or {}
        prior_iso = str(item.get("last_at") or "")
        if not prior_iso:  # pragma: no cover - defensive: CCFE without row
            raise
        prior_dt = datetime.fromisoformat(prior_iso.replace("Z", "+00:00"))
        elapsed = (now - prior_dt).total_seconds()
        retry_after = max(1, int(cooldown_seconds - elapsed))
        raise ExportTooSoonError(retry_after=retry_after) from exc


def _timedelta_seconds(seconds: int) -> Any:
    """Return a timedelta — wrapped in a helper so tests can mock
    if needed."""
    from datetime import timedelta

    return timedelta(seconds=seconds)


# ---- Read paths used by the export ---------------------------------


def get_friendships(user_id: str) -> list[dict[str, Any]]:
    """Return every friendship row touching ``user_id`` (both sides
    of the canonical pair).

    Returns a list of ``{friend_user_id, since}`` dicts. ``since``
    is the ISO created_at of the friendship.
    """
    table = _table()
    rows: list[dict[str, Any]] = []
    # Side A: PK = USER#<min(a,b)>, SK begins_with FRIEND# — friend is on the SK.
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":sk": "FRIEND#",
        },
    )
    for item in response.get("Items") or []:
        sk = str(item["SK"])
        rows.append(
            {
                "friend_user_id": sk.removeprefix("FRIEND#"),
                "since": str(item["created_at"]),
            }
        )
    # Side B: GSI1PK = USER#<max(a,b)>, GSI1SK begins_with FRIEND# —
    # friend is on the GSI1SK.
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            "GSI1PK = :pk AND begins_with(GSI1SK, :sk)"
        ),
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":sk": "FRIEND#",
        },
    )
    for item in response.get("Items") or []:
        sk = str(item["GSI1SK"])
        rows.append(
            {
                "friend_user_id": sk.removeprefix("FRIEND#"),
                "since": str(item["created_at"]),
            }
        )
    return rows
