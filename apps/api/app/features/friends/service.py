"""Business logic for the friends feature.

The service layer orchestrates rate-limit, repository, and policy
checks; routes (in :mod:`app.features.friends.routes`) just adapt the
service to HTTP shapes.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.observability import logger
from app.features.friends import repository as repo
from app.features.friends.cursor import (
    InvalidCursorError as CursorDecodeError,
)
from app.features.friends.cursor import (
    decode as decode_cursor,
)
from app.features.friends.cursor import (
    encode as encode_cursor,
)
from app.features.friends.errors import (
    ConflictError,
    InvalidCursorError,
    RateLimitedError,
    SelfActionForbiddenError,
    SelfAddForbiddenError,
    UserNotFoundError,
)
from app.features.friends.models import (
    AddFriendResponse,
    FriendBalanceResponse,
    FriendItem,
    ListFriendsResponse,
)
from app.features.friends.rate_limit import (
    FriendAddRateLimitExceeded,
    consume_friend_add,
)


def add_friend(*, requester_id: str, email: str) -> AddFriendResponse:
    """Add a friend by email.

    Order is load-bearing for the privacy story:
    1. Rate-limit FIRST (closes email-existence enumeration oracle).
    2. Lookup target by email-hash GSI1.
    3. Self-add guard.
    4. TransactWriteItems with `attribute_not_exists(PK)` cond.
    5. Read target META for the response.
    """
    try:
        consume_friend_add(requester_id)
    except FriendAddRateLimitExceeded as exc:
        raise RateLimitedError(retry_after_seconds=exc.retry_after_seconds) from exc

    target_id = repo.find_user_by_email(email)
    if target_id is None:
        logger.info(
            "friend_add_user_not_found",
            extra={"requester_id": requester_id},
        )
        raise UserNotFoundError()

    if target_id == requester_id:
        logger.info(
            "friend_add_self",
            extra={"requester_id": requester_id},
        )
        raise SelfAddForbiddenError()

    try:
        created_at = repo.create_friendship(
            requester_id, target_id, created_by=requester_id
        )
    except repo.ConflictError as exc:
        logger.info(
            "friend_add_conflict",
            extra={"requester_id": requester_id, "friend_id": target_id},
        )
        raise ConflictError() from exc

    meta = repo.get_user_meta(target_id)
    if meta is None:
        # Defensive: GSI1 lookup hit but the META row vanished mid-request.
        # Log and return a 500 by surfacing as ``UserNotFoundError`` —
        # we'd rather report "no such user" than a fictional success.
        logger.error(
            "friend_add_meta_missing_post_create",
            extra={"requester_id": requester_id, "friend_id": target_id},
        )
        raise UserNotFoundError()

    logger.info(
        "friend_added",
        extra={"requester_id": requester_id, "friend_id": target_id},
    )
    return AddFriendResponse(
        user_id=target_id,
        name=meta.name,
        currency=meta.currency,  # type: ignore[arg-type]
        since=created_at,
    )


def list_friends(
    *, requester_id: str, limit: int, cursor: str | None
) -> ListFriendsResponse:
    """List a user's friends, sorted by friend user_id ascending."""
    last_id: str | None = None
    if cursor:
        try:
            last_id = decode_cursor(cursor=cursor, requester_id=requester_id)
        except CursorDecodeError as exc:
            raise InvalidCursorError() from exc

    fetch_limit = limit + 1  # one-past lookahead

    base_rows, base_more = repo.query_one_side(
        requester_id, side="base", fetch_limit=fetch_limit, last_friend_id=last_id
    )
    gsi_rows, gsi_more = repo.query_one_side(
        requester_id, side="gsi1", fetch_limit=fetch_limit, last_friend_id=last_id
    )

    candidates = sorted(
        base_rows + gsi_rows, key=lambda r: r.friend_user_id
    )

    page = candidates[:limit]
    has_more = (
        len(candidates) > limit
        or (base_more and len(base_rows) >= fetch_limit)
        or (gsi_more and len(gsi_rows) >= fetch_limit)
    )

    next_cursor: str | None = None
    if has_more and page:
        next_cursor = encode_cursor(
            requester_id=requester_id, last_friend_id=page[-1].friend_user_id
        )

    metas = repo.batch_get_user_metas([row.friend_user_id for row in page])
    items: list[FriendItem] = []
    for row in page:
        meta = metas.get(row.friend_user_id)
        if meta is None:
            # The friend's META row is missing — skip silently. Should
            # be impossible given Phase 2c's META-row invariant; if it
            # ever happens, alert via metric in Phase 6.
            logger.warning(
                "friend_meta_missing_in_list",
                extra={"requester_id": requester_id, "friend_id": row.friend_user_id},
            )
            continue
        items.append(
            FriendItem(
                user_id=row.friend_user_id,
                name=meta.name,
                currency=meta.currency,  # type: ignore[arg-type]
                since=row.created_at,
            )
        )
    return ListFriendsResponse(items=items, next_cursor=next_cursor)


def remove_friend(*, requester_id: str, target_id: str) -> None:
    """Hard-delete the canonical-pair friendship row."""
    if target_id == requester_id:
        raise SelfActionForbiddenError()
    if not repo.delete_friendship(requester_id, target_id):
        raise UserNotFoundError()
    logger.info(
        "friend_removed",
        extra={"requester_id": requester_id, "friend_id": target_id},
    )


def get_balance(
    *, requester_id: str, target_id: str
) -> FriendBalanceResponse:
    """Return the balance with a friend.

    Phase 3a returns zeros / null. Phase 4 fills in real numbers.
    """
    if target_id == requester_id:
        raise SelfActionForbiddenError()
    if not repo.friendship_exists(requester_id, target_id):
        raise UserNotFoundError()
    me = repo.get_user_meta(requester_id)
    # The requester's META must exist because they're authenticated and
    # signed up via Phase 2c. Defensive fallback to USD if it's somehow
    # missing.
    currency = me.currency if me else "USD"
    return FriendBalanceResponse(
        user_id=target_id,
        currency=currency,  # type: ignore[arg-type]
        net=Decimal("0.00"),
        settlement_status="settled",
        last_transaction_at=None,
    )


