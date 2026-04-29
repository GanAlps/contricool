"""FastAPI router for ``/v1/friends/*``.

Routes are thin adaptors around :mod:`app.features.friends.service`.
All four routes are authenticated via the JWT authorizer + the
Lambda-side ``current_principal`` dependency (Phase 2c).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, status

from app.core.dependencies import current_principal
from app.core.principal import Principal
from app.features.friends import service
from app.features.friends.errors import (
    SelfActionForbiddenError,
    ValidationFailedError,
)
from app.features.friends.models import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AddFriendRequest,
    AddFriendResponse,
    FriendBalanceResponse,
    ListFriendsQuery,
    ListFriendsResponse,
)

# ULID Crockford alphabet: 26 chars, [0-9A-HJKMNP-TV-Z], no I/L/O/U.
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _validate_user_id(user_id: str) -> str:
    """Validate the path param shape; non-ULID → 422 ``VALIDATION_ERROR``."""
    if not _ULID_RE.fullmatch(user_id):
        raise ValidationFailedError(
            field="user_id",
            issue="must be a 26-character Crockford ULID",
        )
    return user_id


router = APIRouter(prefix="/friends", tags=["friends"])


@router.post(
    "/add",
    status_code=status.HTTP_200_OK,
    response_model=AddFriendResponse,
)
def add_friend_route(
    body: AddFriendRequest,
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> AddFriendResponse:
    return service.add_friend(
        requester_id=principal.user_id, email=body.email
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ListFriendsResponse,
)
def list_friends_route(
    query: ListFriendsQuery = Depends(),  # noqa: B008
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> ListFriendsResponse:
    return service.list_friends(
        requester_id=principal.user_id,
        limit=query.limit or DEFAULT_LIMIT,
        cursor=query.cursor,
    )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def remove_friend_route(
    user_id: str,
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> None:
    user_id = _validate_user_id(user_id)
    if user_id == principal.user_id:
        raise SelfActionForbiddenError()
    service.remove_friend(requester_id=principal.user_id, target_id=user_id)


@router.get(
    "/{user_id}/balance",
    status_code=status.HTTP_200_OK,
    response_model=FriendBalanceResponse,
)
def get_friend_balance_route(
    user_id: str,
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> FriendBalanceResponse:
    user_id = _validate_user_id(user_id)
    if user_id == principal.user_id:
        raise SelfActionForbiddenError()
    return service.get_balance(
        requester_id=principal.user_id, target_id=user_id
    )


# Silence ``MAX_LIMIT`` unused-import warning when bumped.
_ = MAX_LIMIT
