"""``/v1/me`` routes — Phase 7 account self-service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import current_principal
from app.core.principal import Principal
from app.features.me import service
from app.features.me.models import ExportResponse

router = APIRouter(prefix="/me", tags=["me"])


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_my_account_route(
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> Response:
    """Soft-deactivate the current user.

    Idempotent: a second call still returns 204. Cognito disable +
    global-sign-out fire on every call so a half-applied prior
    attempt heals on retry.
    """
    service.delete_my_account(
        requester_id=principal.user_id,
        requester_email=principal.email,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    response_model=ExportResponse,
)
def export_my_data_route(
    principal: Principal = Depends(current_principal),  # noqa: B008
) -> ExportResponse:
    """JSON dump of the requester's data.

    Rate-limited to one export per 24 h per user; subsequent calls
    return 429 ``RATE_LIMITED`` with ``retry_after`` in seconds.
    """
    return service.export_my_data(requester_id=principal.user_id)
