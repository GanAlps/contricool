"""FastAPI middleware: request ID injection + structured access log.

The middleware:

- Reads ``X-Request-Id`` if the client supplied a ULID-shaped value;
  otherwise generates a fresh ULID.
- Stores the value on ``request.state.request_id`` for downstream
  handlers to correlate calls.
- Emits one INFO log line per request after the response is built, with
  ``status_code`` + ``duration_ms``. The Powertools Logger redaction layer
  applies — feature handlers MUST NOT pass raw bodies, headers, or query
  strings into the logger; this middleware deliberately logs none of
  those.

JWT handling is out of scope for Phase 2b — Phase 2c adds a
``current_principal()`` dependency that runs JWT verification and
constructs an ``app.core.principal.Principal``.
"""
from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

import ulid
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.observability import logger

# ULID Crockford-base32 alphabet (excludes I, L, O, U).
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class CoreMiddleware(BaseHTTPMiddleware):
    """Inject request ID + emit access log."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = self._extract_or_generate_id(request)
        request.state.request_id = request_id
        logger.append_keys(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )
        started_ns = time.monotonic_ns()
        status_code: int
        try:
            response = await call_next(request)
            status_code = response.status_code
        except BaseException:
            # Surface the failure as a 5xx access-log line before the
            # exception bubbles out; the exception message itself is
            # routed via Powertools' default handler (with redaction).
            status_code = 500
            logger.exception("request failed")
            raise
        finally:
            duration_ms = round(
                (time.monotonic_ns() - started_ns) / 1_000_000, 2
            )
            logger.info(
                "request",
                extra={
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            logger.remove_keys(["request_id", "path", "method"])

        response.headers["X-Request-Id"] = request_id
        return response

    @staticmethod
    def _extract_or_generate_id(request: Request) -> str:
        candidate = (request.headers.get("x-request-id") or "").strip()
        if candidate and _ULID_RE.match(candidate):
            return candidate
        return str(ulid.ULID())


def install_core_middleware(app: FastAPI) -> None:
    """Attach :class:`CoreMiddleware` to a FastAPI app."""
    app.add_middleware(CoreMiddleware)
