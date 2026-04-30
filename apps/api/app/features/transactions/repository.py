"""DDB operations for the transactions feature.

Two tables, one feature:

- ``ContriCool-Users-<env>`` — friendship rows (read in
  ``ConditionCheck`` operands inside the create transact).
- ``ContriCool-Transactions-<env>`` — META, MEMBER, AUDIT, IDEMPOTENCY
  rows (Pattern #7-#12 from Design 7).

Item layout (recap):

| Item        | PK                              | SK                       |
|-------------|---------------------------------|--------------------------|
| META        | ``TXN#<txn_id>``                | ``META``                 |
| MEMBER      | ``TXN#<txn_id>``                | ``MEMBER#<user_id>``     |
| AUDIT       | ``TXN#<txn_id>``                | ``AUDIT#<version_ulid>`` |
| IDEMPOTENCY | ``IDEMPOTENCY#<user>#<key>``    | ``META``                 |

The MEMBER rows carry GSI1 pivots (``GSI1PK = USER#<user_id>``,
``GSI1SK = TXN#<YYYY-MM-DD>#<txn_id>``) so Pattern #8 ("my
transactions, newest first") is one ``Query`` against GSI1.

Cross-table create uses ``TransactWriteItems`` so the friendship
verification, the META/MEMBER/AUDIT writes, and the idempotency
record all commit atomically — or none of them do.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import boto3
from botocore.exceptions import ClientError
from ulid import ULID

from app.core import config
from app.features.transactions.errors import NotFriendError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.service_resource import Table


_GSI1 = "GSI1"

# 24-hour TTL on idempotency rows (Design 7).
_IDEMPOTENCY_TTL_SECONDS = 24 * 3600


# ---- module-scope client/table caches --------------------------------


_default_resource: Any | None = None
_default_users_table: Any | None = None
_default_transactions_table: Any | None = None
_default_client: Any | None = None


def _resource() -> Any:
    global _default_resource
    if _default_resource is None:
        cfg = config.load()
        _default_resource = boto3.resource("dynamodb", region_name=cfg.aws_region)
    return _default_resource


def _client() -> DynamoDBClient:
    # Tests inject a real moto client via ``_set_tables_for_tests``; the
    # production cold-start path below builds one on first use. Marked
    # defensive because the integration tests always pre-populate the
    # cache.
    global _default_client
    if _default_client is None:  # pragma: no cover - production cold-start path
        cfg = config.load()
        _default_client = boto3.client("dynamodb", region_name=cfg.aws_region)
    return cast("DynamoDBClient", _default_client)


def _users_table() -> Table:
    global _default_users_table
    if _default_users_table is None:  # pragma: no cover - production cold-start path
        cfg = config.load()
        _default_users_table = _resource().Table(cfg.users_table_name)
    return cast("Table", _default_users_table)


def _transactions_table() -> Table:
    global _default_transactions_table
    if _default_transactions_table is None:  # pragma: no cover - production cold-start path
        cfg = config.load()
        _default_transactions_table = _resource().Table(cfg.transactions_table_name)
    return cast("Table", _default_transactions_table)


def _set_tables_for_tests(
    *,
    users: Table | None = None,
    transactions: Table | None = None,
    client: Any | None = None,
) -> None:
    """Inject moto-backed table refs for tests; pass ``None`` to clear."""
    global _default_users_table, _default_transactions_table, _default_resource, _default_client
    _default_users_table = users
    _default_transactions_table = transactions
    _default_client = client
    if users is None and transactions is None:
        _default_resource = None


# ---- helpers ---------------------------------------------------------


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def new_txn_id() -> str:
    """Return a new ULID for a transaction."""
    return str(ULID())


def new_audit_id() -> str:
    return str(ULID())


# ---- Read paths ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TxnMetaRow:
    txn_id: str
    creator_id: str
    name: str
    type: str
    amount: Decimal
    currency: str
    txn_date: str
    note: str
    split_method: str
    payers: list[dict[str, Any]]
    member_ids: list[str]
    created_at: str
    updated_at: str
    deleted_at: str | None


@dataclass(frozen=True, slots=True)
class TxnMemberRow:
    txn_id: str
    user_id: str
    owed_amount: Decimal
    share: Decimal | None
    percent: Decimal | None


def get_meta(txn_id: str) -> TxnMetaRow | None:
    response = _transactions_table().get_item(
        Key={"PK": f"TXN#{txn_id}", "SK": "META"}
    )
    item = response.get("Item")
    if not item:
        return None
    return _meta_from_item(item)


def get_members(txn_id: str) -> list[TxnMemberRow]:
    response = _transactions_table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": f"TXN#{txn_id}",
            ":sk": "MEMBER#",
        },
    )
    return [_member_from_item(item) for item in response.get("Items") or []]


def query_user_member_rows(
    user_id: str,
    *,
    limit: int,
    last_gsi1_sk: str | None = None,
) -> tuple[list[tuple[str, str]], str | None]:
    """Return ``(txn_id, gsi1sk)`` pairs for a user, newest first.

    Pattern #8: ``GSI1PK = USER#<id>``, ``begins_with(GSI1SK, "TXN#")``,
    ScanIndexForward=False. Returns the per-row ``GSI1SK`` so the caller
    can pass the last one back as a cursor anchor.
    """
    kwargs: dict[str, Any] = {
        "IndexName": _GSI1,
        "KeyConditionExpression": "GSI1PK = :pk AND begins_with(GSI1SK, :sk)",
        "ExpressionAttributeValues": {
            ":pk": f"USER#{user_id}",
            ":sk": "TXN#",
        },
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if last_gsi1_sk is not None:
        # ExclusiveStartKey for the GSI1 query needs both the base PK/SK
        # and the GSI1 keys. We pass the most recently-seen GSI1SK as the
        # explicit start key.
        kwargs["ExclusiveStartKey"] = {
            "PK": _txn_pk_from_gsi1sk(last_gsi1_sk),
            "SK": f"MEMBER#{user_id}",
            "GSI1PK": f"USER#{user_id}",
            "GSI1SK": last_gsi1_sk,
        }
    response = _transactions_table().query(**kwargs)
    rows: list[tuple[str, str]] = []
    for item in response.get("Items") or []:
        gsi1sk = str(item["GSI1SK"])
        # GSI1SK = TXN#<YYYY-MM-DD>#<txn_id>
        parts = gsi1sk.split("#")
        if len(parts) >= 3:
            rows.append((parts[2], gsi1sk))
    return rows, str(response.get("LastEvaluatedKey", {}).get("GSI1SK") or "") or None


def _txn_pk_from_gsi1sk(gsi1sk: str) -> str:
    parts = gsi1sk.split("#")
    return f"TXN#{parts[2]}" if len(parts) >= 3 else gsi1sk


def batch_get_metas(txn_ids: list[str]) -> dict[str, TxnMetaRow]:
    """Hydrate META rows for a page of txn_ids."""
    if not txn_ids:
        return {}
    cfg = config.load()
    resource = _resource()
    keys = [{"PK": f"TXN#{tid}", "SK": "META"} for tid in txn_ids]
    response = resource.batch_get_item(
        RequestItems={cfg.transactions_table_name: {"Keys": keys}}
    )
    items = response.get("Responses", {}).get(cfg.transactions_table_name, [])
    return {row.txn_id: row for row in (_meta_from_item(item) for item in items)}


def get_idempotency_record(*, user_id: str, key: str) -> dict[str, Any] | None:
    response = _transactions_table().get_item(
        Key={"PK": f"IDEMPOTENCY#{user_id}#{key}", "SK": "META"}
    )
    return response.get("Item")


# ---- Item-shape helpers ---------------------------------------------


def _meta_from_item(item: dict[str, Any]) -> TxnMetaRow:
    return TxnMetaRow(
        txn_id=str(item["PK"]).removeprefix("TXN#"),
        creator_id=str(item["creator_id"]),
        name=str(item["name"]),
        type=str(item["type"]),
        amount=Decimal(str(item["amount"])),
        currency=str(item["currency"]),
        txn_date=str(item["txn_date"]),
        note=str(item.get("note") or ""),
        split_method=str(item["split_method"]),
        payers=list(item.get("payers") or []),
        member_ids=list(item.get("member_ids") or []),
        created_at=str(item["created_at"]),
        updated_at=str(item["updated_at"]),
        deleted_at=(
            str(item["deleted_at"]) if item.get("deleted_at") else None
        ),
    )


def _member_from_item(item: dict[str, Any]) -> TxnMemberRow:
    sk = str(item["SK"])
    return TxnMemberRow(
        txn_id=str(item["PK"]).removeprefix("TXN#"),
        user_id=sk.removeprefix("MEMBER#"),
        owed_amount=Decimal(str(item["owed_amount"])),
        share=(
            Decimal(str(item["share"])) if item.get("share") is not None else None
        ),
        percent=(
            Decimal(str(item["percent"])) if item.get("percent") is not None else None
        ),
    )


# ---- Cross-table create ---------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateInputs:
    creator_id: str
    name: str
    type: str
    amount: Decimal
    currency: str
    txn_date: str
    note: str
    split_method: str
    members: list[dict[str, Any]]  # each: user_id, owed_amount, share?, percent?
    payers: list[dict[str, Any]]   # each: user_id, paid_amount


@dataclass(frozen=True, slots=True)
class CreateResult:
    txn_id: str
    created_at: datetime
    updated_at: datetime
    audit_id: str


@dataclass(frozen=True, slots=True)
class IdempotencyHit:
    """Returned when a TransactWriteItems aborts on the IDEMPOTENCY
    `attribute_not_exists` condition — the caller maps to the cached
    response."""

    record: dict[str, Any]


def _to_ddb_value(v: Any) -> Any:
    """boto3 ``Table`` resource takes Python types directly; nothing
    to do — but we centralise here so the call sites read uniformly.
    """
    return v


def create_transaction(
    *,
    inputs: CreateInputs,
    idempotency_key: str,
    request_hash: str,
    response_payload_factory: Any,
    txn_id: str | None = None,
    created_at: datetime | None = None,
) -> CreateResult | IdempotencyHit:
    """Create a transaction atomically with friendship checks +
    idempotency record.

    Parameters
    ----------
    response_payload_factory
        Callable ``(txn_id, created_at, updated_at) -> dict`` that
        produces the response body to embed in the IDEMPOTENCY row.
        Threaded as a callable so the cached payload reflects the
        same ``txn_id`` / timestamps that the META row records.
    txn_id
        Optional caller-supplied ULID; if absent the repo mints one.
        Tests use this to assert deterministic behaviour.
    created_at
        Optional caller-supplied creation timestamp; if absent the
        repo uses ``datetime.now(UTC)``.
    """
    cfg = config.load()
    if txn_id is None:
        txn_id = new_txn_id()
    audit_id = new_audit_id()
    if created_at is None:
        created_at = _now_utc()
    iso_now = _iso(created_at)
    response_payload = response_payload_factory(txn_id, created_at, created_at)

    other_member_ids = [
        m["user_id"] for m in inputs.members if m["user_id"] != inputs.creator_id
    ]
    member_ids_sorted = sorted(m["user_id"] for m in inputs.members)

    # Build the META item.
    meta_item: dict[str, Any] = {
        "PK": {"S": f"TXN#{txn_id}"},
        "SK": {"S": "META"},
        "creator_id": {"S": inputs.creator_id},
        "name": {"S": inputs.name},
        "type": {"S": inputs.type},
        "amount": {"N": str(inputs.amount)},
        "currency": {"S": inputs.currency},
        "txn_date": {"S": inputs.txn_date},
        "note": {"S": inputs.note or ""},
        "split_method": {"S": inputs.split_method},
        "payers": {
            "L": [
                {
                    "M": {
                        "user_id": {"S": p["user_id"]},
                        "paid_amount": {"N": str(p["paid_amount"])},
                    }
                }
                for p in inputs.payers
            ]
        },
        "member_ids": {"L": [{"S": uid} for uid in member_ids_sorted]},
        "created_at": {"S": iso_now},
        "updated_at": {"S": iso_now},
    }

    member_items: list[dict[str, Any]] = []
    for m in inputs.members:
        item: dict[str, Any] = {
            "PK": {"S": f"TXN#{txn_id}"},
            "SK": {"S": f"MEMBER#{m['user_id']}"},
            "GSI1PK": {"S": f"USER#{m['user_id']}"},
            "GSI1SK": {"S": f"TXN#{inputs.txn_date}#{txn_id}"},
            "owed_amount": {"N": str(m["owed_amount"])},
        }
        if m.get("share") is not None:
            item["share"] = {"N": str(m["share"])}
        if m.get("percent") is not None:
            item["percent"] = {"N": str(m["percent"])}
        member_items.append(item)

    audit_item: dict[str, Any] = {
        "PK": {"S": f"TXN#{txn_id}"},
        "SK": {"S": f"AUDIT#{audit_id}"},
        "action": {"S": "create"},
        "actor_id": {"S": inputs.creator_id},
        "at": {"S": iso_now},
        "snapshot": {
            "S": json.dumps(
                {
                    "members": [
                        {
                            "user_id": m["user_id"],
                            "owed_amount": str(m["owed_amount"]),
                            "share": (
                                str(m["share"]) if m.get("share") is not None else None
                            ),
                            "percent": (
                                str(m["percent"])
                                if m.get("percent") is not None
                                else None
                            ),
                        }
                        for m in inputs.members
                    ],
                    "payers": [
                        {
                            "user_id": p["user_id"],
                            "paid_amount": str(p["paid_amount"]),
                        }
                        for p in inputs.payers
                    ],
                    "name": inputs.name,
                    "amount": str(inputs.amount),
                    "currency": inputs.currency,
                    "txn_date": inputs.txn_date,
                    "type": inputs.type,
                    "split_method": inputs.split_method,
                    "note": inputs.note or "",
                }
            )
        },
    }

    expires_at = int(created_at.timestamp()) + _IDEMPOTENCY_TTL_SECONDS
    idempotency_item: dict[str, Any] = {
        "PK": {"S": f"IDEMPOTENCY#{inputs.creator_id}#{idempotency_key}"},
        "SK": {"S": "META"},
        "txn_id": {"S": txn_id},
        "request_hash": {"S": request_hash},
        "response": {"S": json.dumps(response_payload, default=str)},
        "status_code": {"N": "201"},
        "ttl": {"N": str(expires_at)},
    }

    # Build the friendship ConditionChecks: every other-member must
    # have a canonical-pair friendship row with the creator.
    transact_items: list[dict[str, Any]] = []
    for other_id in other_member_ids:
        min_id, max_id = _canonical_pair(inputs.creator_id, other_id)
        transact_items.append(
            {
                "ConditionCheck": {
                    "TableName": cfg.users_table_name,
                    "Key": {
                        "PK": {"S": f"USER#{min_id}"},
                        "SK": {"S": f"FRIEND#{max_id}"},
                    },
                    "ConditionExpression": "attribute_exists(PK)",
                }
            }
        )
    transact_items.append(
        {
            "Put": {
                "TableName": cfg.transactions_table_name,
                "Item": meta_item,
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
    )
    for member_item in member_items:
        transact_items.append(
            {
                "Put": {
                    "TableName": cfg.transactions_table_name,
                    "Item": member_item,
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        )
    transact_items.append(
        {
            "Put": {
                "TableName": cfg.transactions_table_name,
                "Item": audit_item,
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
    )
    # Idempotency slot LAST so a same-key replay surfaces as a
    # ConditionalCheckFailed on a known position (the last one).
    transact_items.append(
        {
            "Put": {
                "TableName": cfg.transactions_table_name,
                "Item": idempotency_item,
                "ConditionExpression": "attribute_not_exists(PK)",
            }
        }
    )

    try:
        _client().transact_write_items(TransactItems=transact_items)  # type: ignore[arg-type]
    except ClientError as exc:
        return _decode_transact_error(
            exc,
            other_member_count=len(other_member_ids),
            user_id=inputs.creator_id,
            key=idempotency_key,
        )

    return CreateResult(
        txn_id=txn_id,
        created_at=created_at,
        updated_at=created_at,
        audit_id=audit_id,
    )


def _decode_transact_error(
    exc: ClientError,
    *,
    other_member_count: int,
    user_id: str,
    key: str,
) -> CreateResult | IdempotencyHit:
    """Decode a TransactionCanceledException's per-item reasons.

    Slot order (matching ``create_transaction`` above):

    - ``[0:other_member_count]`` — friendship ConditionChecks.
    - ``[other_member_count]``   — META Put.
    - ``[other_member_count+1:other_member_count+1+N]`` — MEMBER Puts.
    - ``[..]`` — AUDIT Put.
    - last slot — IDEMPOTENCY Put.

    A ``ConditionalCheckFailed`` reason at any friendship slot →
    :class:`NotFriendError`. At the IDEMPOTENCY slot → return the
    cached record.
    """
    code = exc.response.get("Error", {}).get("Code", "")
    if code != "TransactionCanceledException":
        raise exc
    reasons = exc.response.get("CancellationReasons") or []
    if not reasons:
        raise exc
    # Friendship check failures are the first ``other_member_count`` slots.
    for i in range(other_member_count):
        if (
            i < len(reasons)
            and reasons[i].get("Code") == "ConditionalCheckFailed"
        ):
            raise NotFriendError() from exc
    # The last slot is the IDEMPOTENCY put.
    last_idx = len(reasons) - 1
    if (
        last_idx >= 0
        and reasons[last_idx].get("Code") == "ConditionalCheckFailed"
    ):
        record = get_idempotency_record(user_id=user_id, key=key)
        if record is None:  # pragma: no cover - unreachable in practice
            raise exc
        return IdempotencyHit(record=record)
    raise exc


def get_friendship_ids(creator_id: str, other_ids: list[str]) -> set[str]:
    """Return the subset of ``other_ids`` that are currently friends of
    ``creator_id``. Used as a cheap pre-flight before the transact so a
    bad request fails-fast with NOT_FRIEND rather than racing through
    DDB.
    """
    if not other_ids:
        return set()
    table = _users_table()
    friend_ids: set[str] = set()
    for other in other_ids:
        min_id, max_id = _canonical_pair(creator_id, other)
        response = table.get_item(
            Key={"PK": f"USER#{min_id}", "SK": f"FRIEND#{max_id}"},
            ProjectionExpression="PK",
        )
        if "Item" in response:
            friend_ids.add(other)
    return friend_ids


def get_user_currencies(user_ids: list[str]) -> dict[str, str]:
    """Fetch each user's ``currency`` attribute via BatchGetItem."""
    if not user_ids:
        return {}
    cfg = config.load()
    keys = [{"PK": f"USER#{uid}", "SK": "META"} for uid in user_ids]
    response = _resource().batch_get_item(
        RequestItems={
            cfg.users_table_name: {
                "Keys": keys,
                "ProjectionExpression": "PK, currency",
            }
        }
    )
    out: dict[str, str] = {}
    for item in (
        response.get("Responses", {}).get(cfg.users_table_name) or []
    ):
        uid = str(item["PK"]).removeprefix("USER#")
        out[uid] = str(item["currency"])
    return out
