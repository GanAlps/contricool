"""FastAPI dependencies that turn validated JWTs into a ``Principal``.

``current_principal`` is the only authenticated-route entry point a
feature handler needs. It:

1. Reads the ``Authorization: Bearer …`` header.
2. Verifies the token via :class:`app.core.security.JwtVerifier`.
3. Constructs a :class:`app.core.principal.Principal` from the claims.

Any failure surfaces as :class:`UnauthenticatedError`, which the global
exception handler maps to a generic 401 ``UNAUTHENTICATED`` envelope —
we never tell the attacker which check failed.

The verifier is cached in module scope. The first dependency call after
cold start builds it from ``app.core.config`` (which has already loaded
the per-env Cognito pool ID + the three app-client IDs from SSM). Tests
inject a custom verifier via :func:`set_verifier_for_tests`.
"""
from __future__ import annotations

import threading

from fastapi import Request

from app.core import config
from app.core.observability import logger
from app.core.principal import Principal
from app.core.security import InvalidTokenError, JwtVerifier


class UnauthenticatedError(Exception):
    """Caller is missing or has an invalid bearer token."""


_verifier: JwtVerifier | None = None
_lock = threading.Lock()


def get_jwt_verifier() -> JwtVerifier:
    """Return the module-scope verifier, building it on first call."""
    global _verifier
    if _verifier is not None:
        return _verifier
    with _lock:
        if _verifier is not None:  # pragma: no cover - rare thread race
            return _verifier
        cfg = config.load()
        _verifier = JwtVerifier(
            issuer=(
                f"https://cognito-idp.{cfg.aws_region}.amazonaws.com/"
                f"{cfg.cognito_user_pool_id}"
            ),
            audience_ids=[
                cfg.cognito_web_client_id,
                cfg.cognito_ios_client_id,
                cfg.cognito_android_client_id,
            ],
        )
        return _verifier


def set_verifier_for_tests(verifier: JwtVerifier | None) -> None:
    """Inject a custom verifier (or clear the cache) for tests."""
    global _verifier
    _verifier = verifier


async def current_principal(request: Request) -> Principal:
    """FastAPI dependency: returns the authenticated :class:`Principal`.

    Raises :class:`UnauthenticatedError` for any failure path; the
    global handler translates to 401.

    On every failure path we emit a single WARN log line whose payload
    is *strictly* operator-debuggable metadata: the failure stage, the
    underlying exception class name, and the ``token_use`` (only when
    the token decoded far enough for that to be readable). We never
    log the token, the email, the kid, or any claim value — so an
    attacker can't probe what the verifier dislikes about a forged
    token, but the on-call still has enough to diagnose the real
    operational failures (rotated JWKs, wrong audience config, bad
    Principal claims) that previously surfaced as unexplained 401s.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        logger.warning(
            "auth.principal.failed",
            extra={"stage": "header", "reason": "missing_or_malformed_bearer"},
        )
        raise UnauthenticatedError("missing or malformed Authorization header")

    token = auth_header[len("Bearer ") :].strip()
    if not token:
        logger.warning(
            "auth.principal.failed",
            extra={"stage": "header", "reason": "empty_bearer_token"},
        )
        raise UnauthenticatedError("empty bearer token")

    verifier = get_jwt_verifier()
    try:
        claims = verifier.verify(token)
    except InvalidTokenError as exc:
        cause = exc.__cause__
        logger.warning(
            "auth.principal.failed",
            extra={
                "stage": "verify",
                "reason": str(exc),
                "cause_type": type(cause).__name__ if cause is not None else None,
            },
        )
        raise UnauthenticatedError("token verification failed") from exc

    # Authorization carries the **id token** for ContriCool. Real Cognito
    # access tokens omit ``email``, ``name``, and ``custom:user_id`` —
    # ``Principal.from_claims`` cannot be built from them. The two
    # endpoints that *do* need the access token (``/v1/auth/logout`` for
    # ``GlobalSignOut``) read it from ``X-Cognito-Access-Token``. Reject
    # access tokens here explicitly so the 401 reason is precise rather
    # than a downstream "missing claim" surprise.
    if claims.get("token_use") != "id":
        raise UnauthenticatedError("Authorization must carry an id token")

    try:
        return Principal.from_claims(claims)
    except ValueError as exc:
        # A token that verifies cryptographically but lacks
        # ``custom:user_id`` is an operational bug, not an attacker —
        # but from the caller's perspective they still get 401, and
        # the access-log line carries the request_id for triage.
        logger.warning(
            "auth.principal.failed",
            extra={
                "stage": "principal",
                "reason": str(exc),
                "token_use": claims.get("token_use"),
            },
        )
        raise UnauthenticatedError("principal construction failed") from exc
