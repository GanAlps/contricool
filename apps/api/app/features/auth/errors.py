"""Auth feature error model + global exception handlers.

Every auth-feature failure boils down to an :class:`AuthError` —
``code`` is one of the stable values listed in Design 8's error table
(``UNAUTHENTICATED``, ``EMAIL_EXISTS``, ``RATE_LIMITED``, …),
``http_status`` is the matching status code, ``message`` is
user-facing-safe (no PII), and ``details`` carries optional field-level
validation hints. ``retry_after`` produces a ``Retry-After`` response
header on 429s.

The handlers also map:

- :class:`app.core.dependencies.UnauthenticatedError` → flat 401 envelope.
- :class:`fastapi.exceptions.RequestValidationError` → 422 envelope with
  Pydantic field paths normalised into ``details``.
- Any other unhandled exception → 500 ``INTERNAL`` (response body free
  of any detail; the access-log line carries the request_id for triage).

The envelope shape matches Design 8::

    { "error": { "code", "message", "details"?, "request_id" } }

``request_id`` is read from ``request.state.request_id``, which the
Phase 2b CoreMiddleware populates on every request.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.dependencies import UnauthenticatedError
from app.core.observability import logger


class AuthError(Exception):
    """Stable auth-feature error, mapped 1:1 to the response envelope."""

    def __init__(
        self,
        *,
        code: str,
        http_status: int,
        message: str,
        details: list[dict[str, str]] | None = None,
        retry_after_seconds: int | None = None,
        clear_refresh_cookie: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.details = details
        self.retry_after_seconds = retry_after_seconds
        self.clear_refresh_cookie = clear_refresh_cookie


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or "unknown"


def _envelope(
    *,
    code: str,
    message: str,
    request_id: str,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        payload["details"] = details
    return {"error": payload}


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    headers: dict[str, str] = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(exc.retry_after_seconds)
    response = JSONResponse(
        status_code=exc.http_status,
        content=_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        ),
        headers=headers,
    )
    if exc.clear_refresh_cookie:
        response.delete_cookie(key="rt", path="/v1/auth")
    return response


async def unauthenticated_handler(
    request: Request, _exc: UnauthenticatedError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=_envelope(
            code="UNAUTHENTICATED",
            message="Authentication required.",
            request_id=_request_id(request),
        ),
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details: list[dict[str, str]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        # Drop leading "body" / "query" segment so field paths match the
        # request shape clients send (e.g. "members.2.percent" rather
        # than "body.members.2.percent").
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        field = ".".join(str(p) for p in loc) or "<root>"
        details.append({"field": field, "issue": str(err.get("msg", "invalid"))})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope(
            code="VALIDATION_ERROR",
            message="Request body failed validation.",
            details=details,
            request_id=_request_id(request),
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Type + message logged by Powertools (PII redacted by RedactingFormatter).
    logger.error(
        "unhandled_exception",
        extra={"exc_type": type(exc).__name__},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            code="INTERNAL",
            message="An internal error occurred.",
            request_id=_request_id(request),
        ),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Wire the auth-feature exception handlers into a FastAPI app."""
    app.add_exception_handler(AuthError, auth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(UnauthenticatedError, unauthenticated_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
