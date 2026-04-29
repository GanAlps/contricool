"""DDB operations for the friends feature.

All friendship rows live on ``ContriCool-Users-<env>`` per Design 7
canonical-pair shape::

    PK = USER#<min(a,b)>
    SK = FRIEND#<max(a,b)>
    GSI1PK = USER#<max(a,b)>
    GSI1SK = FRIEND#<min(a,b)>
    created_by, created_at

Email lookup uses the existing GSI1 ``EMAIL#<lookup_hash>`` row class
projected from each user's ``META`` row (Phase 2c).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from app.core import config
from app.core.lookup_hash import email_hash

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


_GSI1 = "GSI1"


class ConflictError(Exception):
    """Raised when ``create_friendship`` fails its
    ``attribute_not_exists`` condition (the friendship already exists)."""


@dataclass(frozen=True, slots=True)
class UserMeta:
    user_id: str
    name: str
    currency: str


@dataclass(frozen=True, slots=True)
class FriendRow:
    """One side of the canonical-pair friendship view, post-merge."""

    friend_user_id: str
    created_at: datetime


_default_table: Table | None = None
_default_resource: object | None = None


def _ddb_resource() -> object:
    """Module-scope DDB resource, re-used across all repository ops
    (Table + BatchGetItem) so we don't rebuild ``boto3.resource`` on
    every call."""
    global _default_resource
    if _default_resource is None:
        cfg = config.load()
        _default_resource = boto3.resource("dynamodb", region_name=cfg.aws_region)
    return _default_resource


def _table() -> Table:
    global _default_table
    if _default_table is None:
        cfg = config.load()
        _default_table = _ddb_resource().Table(cfg.users_table_name)  # type: ignore[attr-defined]
    return _default_table


def _set_table_for_tests(table: Table | None) -> None:
    """Inject a moto-backed Table for tests.

    Drops the cached ``boto3.resource`` so a subsequent test that
    patches ``boto3.resource`` rebuilds the resource through the
    patch (per-test isolation).
    """
    global _default_table, _default_resource
    _default_table = table
    _default_resource = None


# ---- User lookups ------------------------------------------------------


def find_user_by_email(email: str) -> str | None:
    """Resolve an email to ``user_id`` via the GSI1 ``EMAIL#<hash>`` row.

    Returns ``None`` when no user has registered that email — including
    the "user signed up but didn't verify" case (the META row + GSI1
    projection are written together in Phase 2c verify-email).

    The auth feature writes ``GSI1SK = "USER#<user_id>"`` (see
    ``auth.service._create_user_meta_row``); we use ``begins_with`` so
    we don't depend on the trailing user_id when reading.
    """
    h = email_hash(email)
    response = _table().query(
        IndexName=_GSI1,
        KeyConditionExpression="GSI1PK = :pk AND begins_with(GSI1SK, :sk)",
        ExpressionAttributeValues={
            ":pk": f"EMAIL#{h}",
            ":sk": "USER#",
        },
        Limit=1,
    )
    items = response.get("Items") or []
    if not items:
        return None
    pk = str(items[0]["PK"])
    return pk.removeprefix("USER#")


def get_user_meta(user_id: str) -> UserMeta | None:
    """Read the META row for ``user_id``."""
    response = _table().get_item(
        Key={"PK": f"USER#{user_id}", "SK": "META"},
        ProjectionExpression="display_name, currency",
    )
    item = response.get("Item")
    if not item:
        return None
    return UserMeta(
        user_id=user_id,
        name=str(item["display_name"]),
        currency=str(item["currency"]),
    )


_BATCH_GET_MAX_RETRIES = 3


def batch_get_user_metas(user_ids: list[str]) -> dict[str, UserMeta]:
    """Hydrate a batch of friend ids with their (name, currency).

    DDB ``BatchGetItem`` caps at 100 keys per call; ``GET /v1/friends``
    caps ``limit`` at 100 too, so a single call always covers a page
    in steady-state.

    DDB can return ``UnprocessedKeys`` under throttle even when below
    the request size cap. We retry up to ``_BATCH_GET_MAX_RETRIES``
    times on the residual keys; if any keys remain unprocessed after
    that, raise a ``ClientError`` rather than silently dropping
    friends from the page.
    """
    if not user_ids:
        return {}
    cfg = config.load()
    table_name = cfg.users_table_name
    pending = [{"PK": f"USER#{uid}", "SK": "META"} for uid in user_ids]
    resource = _ddb_resource()

    out: dict[str, UserMeta] = {}
    attempts_left = _BATCH_GET_MAX_RETRIES + 1
    while pending and attempts_left > 0:
        attempts_left -= 1
        response = resource.batch_get_item(  # type: ignore[attr-defined]
            RequestItems={
                table_name: {
                    "Keys": pending,
                    "ProjectionExpression": "PK, display_name, currency",
                }
            }
        )
        for item in response.get("Responses", {}).get(table_name, []):
            uid = str(item["PK"]).removeprefix("USER#")
            out[uid] = UserMeta(
                user_id=uid,
                name=str(item["display_name"]),
                currency=str(item["currency"]),
            )
        unprocessed = (
            response.get("UnprocessedKeys", {})
            .get(table_name, {})
            .get("Keys", [])
        )
        pending = list(unprocessed)
    if pending:
        raise ClientError(
            {
                "Error": {
                    "Code": "ProvisionedThroughputExceededException",
                    "Message": (
                        "BatchGetItem returned unprocessed keys after "
                        f"{_BATCH_GET_MAX_RETRIES + 1} attempts; aborting."
                    ),
                }
            },
            "BatchGetItem",
        )
    return out


# ---- Friendship CRUD ---------------------------------------------------


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _friendship_key(a: str, b: str) -> dict[str, str]:
    min_id, max_id = _canonical_pair(a, b)
    return {"PK": f"USER#{min_id}", "SK": f"FRIEND#{max_id}"}


def now_iso() -> tuple[datetime, str]:
    """Return ``(now_dt, "...Z")`` — the canonical timestamp pair used
    by friendship rows and tests. Single source of truth so
    representations stay byte-identical across producer + consumer."""
    now = datetime.now(UTC).replace(microsecond=0)
    return now, now.isoformat().replace("+00:00", "Z")


def create_friendship(a_id: str, b_id: str, *, created_by: str) -> datetime:
    """Insert the canonical-pair friendship row.

    Raises :class:`ConflictError` when the row already exists (the
    ``attribute_not_exists(PK)`` condition fails).

    Returns the ``created_at`` written to the row (UTC, ISO-8601 second
    precision).
    """
    if a_id == b_id:
        raise ValueError("cannot create self-friendship")
    min_id, max_id = _canonical_pair(a_id, b_id)
    now, iso = now_iso()
    item: dict[str, Any] = {
        "PK": f"USER#{min_id}",
        "SK": f"FRIEND#{max_id}",
        "GSI1PK": f"USER#{max_id}",
        "GSI1SK": f"FRIEND#{min_id}",
        "created_by": created_by,
        "created_at": iso,
    }
    try:
        _table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            raise ConflictError("friendship already exists") from e
        raise
    return now


def delete_friendship(a_id: str, b_id: str) -> bool:
    """Hard-delete the canonical-pair friendship row.

    Returns ``True`` if a row was deleted, ``False`` if no friendship
    existed (used by the route to map to 404 ``USER_NOT_FOUND``).
    """
    if a_id == b_id:
        return False
    try:
        _table().delete_item(
            Key=_friendship_key(a_id, b_id),
            ConditionExpression="attribute_exists(PK)",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            return False
        raise
    return True


def friendship_exists(a_id: str, b_id: str) -> bool:
    """Cheap probe used by ``GET /balance`` and ``app/core/policy.is_friend``."""
    if a_id == b_id:
        return False
    response = _table().get_item(
        Key=_friendship_key(a_id, b_id),
        ProjectionExpression="PK",
    )
    return "Item" in response


# ---- Listing ----------------------------------------------------------


def query_one_side(
    user_id: str,
    *,
    side: str,
    fetch_limit: int,
    last_friend_id: str | None,
) -> tuple[list[FriendRow], bool]:
    """Query one side of the polymorphic friendship view.

    ``side`` is ``"base"`` (friends with id > user_id, stored at
    ``PK=USER#<user_id>``) or ``"gsi1"`` (friends with id < user_id,
    stored at ``GSI1PK=USER#<user_id>``).

    Returns ``(rows, has_more)`` where ``rows`` is sorted by friend
    user_id ascending and ``has_more`` is True iff DDB returned a
    ``LastEvaluatedKey``.
    """
    sk_floor = f"FRIEND#{last_friend_id}" if last_friend_id else "FRIEND#"
    op = ">" if last_friend_id else ">="
    values = {":pk": f"USER#{user_id}", ":sk": sk_floor}
    table = _table()
    if side == "base":
        response = table.query(
            KeyConditionExpression=f"PK = :pk AND SK {op} :sk",
            ExpressionAttributeValues=values,
            Limit=fetch_limit,
        )
    elif side == "gsi1":
        response = table.query(
            IndexName=_GSI1,
            KeyConditionExpression=f"GSI1PK = :pk AND GSI1SK {op} :sk",
            ExpressionAttributeValues=values,
            Limit=fetch_limit,
        )
    else:
        raise ValueError(f"unknown side {side!r}")
    rows: list[FriendRow] = []
    for item in response.get("Items") or []:
        # The friend's user_id lives in different attributes depending
        # on which side we queried.
        sk = str(item["SK"] if side == "base" else item["GSI1SK"])
        friend_id = sk.removeprefix("FRIEND#")
        # Stored as `2026-04-29T20:01:45Z`.
        created_at_raw = str(item["created_at"])
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        rows.append(FriendRow(friend_user_id=friend_id, created_at=created_at))
    has_more = "LastEvaluatedKey" in response
    return rows, has_more
