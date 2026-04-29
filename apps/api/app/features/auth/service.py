"""Auth feature business logic — pure of HTTP concerns.

Each public function takes domain types in, returns domain types out,
and raises :class:`AuthError` on any failure. The route layer in
``routes.py`` adapts HTTP request/response and cookie wiring around it.

Why isolate this file from FastAPI? Two reasons:

1. Business-logic tests can run with no FastAPI / TestClient overhead —
   `pytest tests/features/auth/test_service.py` exercises the rules
   directly, much faster.
2. Future workers / scheduled jobs (e.g. nightly cleanup of orphaned
   pending signups) can reuse the same service without dragging the
   web framework along.
"""
from __future__ import annotations

import time
from datetime import UTC
from typing import TYPE_CHECKING

import boto3
import ulid
from botocore.exceptions import ClientError

from app.core import config
from app.core.lookup_hash import email_hash
from app.core.observability import logger
from app.features.auth import cognito_client, rate_limit
from app.features.auth.errors import AuthError
from app.features.auth.models import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LoginUser,
    RefreshResponse,
    ResendEmailCodeRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


_default_table: Table | None = None


def _table() -> Table:
    """Lazy ``ContriCool-Users-<env>`` table accessor."""
    global _default_table
    if _default_table is None:
        cfg = config.load()
        _default_table = boto3.resource(
            "dynamodb", region_name=cfg.aws_region
        ).Table(cfg.users_table_name)
    return _default_table


def _set_table_for_tests(table: Table | None) -> None:
    global _default_table
    _default_table = table


def _cognito() -> cognito_client.CognitoClient:
    cfg = config.load()
    return cognito_client.CognitoClient(user_pool_id=cfg.cognito_user_pool_id)


def _web_client_id() -> str:
    return config.load().cognito_web_client_id


# ---- Signup -----------------------------------------------------------


def signup(req: SignupRequest) -> SignupResponse:
    user_id = str(ulid.ULID())
    attrs: dict[str, str] = {
        "email": req.email,
        "name": req.name,
        "custom:user_id": user_id,
    }
    if req.phone:
        attrs["phone_number"] = req.phone

    try:
        _cognito().sign_up(
            client_id=_web_client_id(),
            email=req.email,
            password=req.password,
            attributes=attrs,
        )
    except AuthError:
        # Re-raise so routes layer turns it into the right envelope.
        # No PII in logs — only the error class name.
        logger.warning("signup_failed", extra={"event": "signup"})
        raise

    logger.info("signup_started", extra={"event": "signup", "user_id": user_id})
    return SignupResponse(user_id=user_id, status="PENDING_VERIFICATION")


# ---- Verify email ----------------------------------------------------


def verify_email(req: VerifyEmailRequest) -> VerifyEmailResponse:
    cognito = _cognito()
    cognito.confirm_sign_up(
        client_id=_web_client_id(),
        email=req.email,
        code=req.code,
    )

    # Read custom:user_id from Cognito so we never trust client-supplied
    # IDs. AdminGetUser is server-only — never exposed beyond this code
    # path.
    attrs = cognito.admin_get_user(email=req.email)
    user_id = attrs.get("custom:user_id")
    if not user_id:
        # Operational anomaly — Cognito user lacks our custom attribute.
        logger.error(
            "verify_email_missing_custom_user_id",
            extra={"event": "verify_email"},
        )
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        )

    name = attrs.get("name", "")
    # ``currency`` is captured at signup-time in the request and lives
    # only in DDB — Cognito doesn't store it. Phase 2c verify-email
    # is the one-shot write of that value, but we don't have the
    # original currency here. The MVP signup flow stores it as a
    # transient signup-state row keyed by email-hash before SignUp;
    # for Phase 2c we accept that the user will set it on first login
    # if missing — write a default and let the profile feature
    # (Phase 3) backfill via PATCH /v1/me. **Decision**: persist
    # ``currency`` from a per-email transient row written at signup
    # time (see ``_signup_pending_currency``).
    currency = _read_pending_currency(req.email)

    _put_user_meta(
        user_id=user_id,
        email=req.email,
        display_name=name,
        currency=currency,
    )
    logger.info(
        "verify_email_completed",
        extra={"event": "verify_email", "user_id": user_id},
    )
    return VerifyEmailResponse(email_verified=True, account_active=True)


def _put_user_meta(
    *, user_id: str, email: str, display_name: str, currency: str
) -> None:
    """Write the USER#<id>#META row idempotently.

    On a duplicate (verify-email called twice), the conditional write
    fails — that's fine, the row is already there.
    """
    table = _table()
    now_iso = _utc_now_iso()
    item = {
        "PK": f"USER#{user_id}",
        "SK": "META",
        "display_name": display_name,
        "currency": currency,
        "status": "active",
        "created_at": now_iso,
        "updated_at": now_iso,
        "GSI1PK": f"EMAIL#{email_hash(email)}",
        "GSI1SK": f"USER#{user_id}",
    }
    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            # Idempotent retry — row already exists. Service treats as
            # success.
            return
        logger.error(
            "verify_email_ddb_write_failed",
            extra={"event": "verify_email", "ddb_error": code},
        )
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        ) from e


def _read_pending_currency(email: str) -> str:
    """Read the per-email signup-pending currency.

    Phase 2c writes a small ``EMAIL#<hash>#PENDING`` row at signup time
    capturing the chosen currency, so that ``verify_email`` can copy it
    into the META row without re-asking the client. The row's TTL is
    7 days — long enough for the user to confirm, short enough that
    abandoned signups don't accumulate.
    """
    table = _table()
    response = table.get_item(
        Key={"PK": f"EMAIL#{email_hash(email)}", "SK": "PENDING"},
    )
    item = response.get("Item") or {}
    currency = str(item.get("currency", "USD"))
    if currency not in ("USD", "INR"):
        currency = "USD"
    return currency


def _write_pending_currency(email: str, currency: str) -> None:
    """Persist the chosen currency until verify-email runs."""
    table = _table()
    table.put_item(
        Item={
            "PK": f"EMAIL#{email_hash(email)}",
            "SK": "PENDING",
            "currency": currency,
            "ttl": int(time.time()) + 7 * 86400,
        },
    )


# Wire the pending-currency write into signup so verify-email can read it.
def signup_with_pending(req: SignupRequest) -> SignupResponse:
    """Public signup that also persists the pending currency."""
    response = signup(req)
    _write_pending_currency(req.email, req.currency)
    return response


# ---- Resend email code -----------------------------------------------


def resend_email_code(req: ResendEmailCodeRequest) -> None:
    """Bumps the rate-limit counter then asks Cognito to resend.

    Errors:
    - :class:`rate_limit.RateLimitExceeded` (caller maps to 429).
    - :class:`AuthError` for everything else.

    Unknown email is **not** an error from the caller's perspective:
    we deliberately swallow ``USER_NOT_FOUND`` to avoid leaking
    enumeration (R3.6).
    """
    rate_limit.consume_otp_email(req.email)
    try:
        _cognito().resend_confirmation_code(
            client_id=_web_client_id(),
            email=req.email,
        )
    except AuthError as e:
        if e.code == "USER_NOT_FOUND":
            return
        raise


# ---- Login ------------------------------------------------------------


def login(req: LoginRequest) -> tuple[LoginResponse, str]:
    """Returns ``(LoginResponse, refresh_token)`` — caller sets cookie."""
    cognito = _cognito()
    tokens = cognito.initiate_auth_user_password(
        client_id=_web_client_id(),
        email=req.email,
        password=req.password,
    )

    # Build the user object from DDB.
    attrs = cognito.admin_get_user(email=req.email)
    user_id = attrs.get("custom:user_id")
    if not user_id:
        logger.error("login_missing_custom_user_id", extra={"event": "login"})
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        )
    meta = _read_user_meta(user_id)
    if not meta:
        logger.error(
            "login_meta_row_missing",
            extra={"event": "login", "user_id": user_id},
        )
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        )

    response = LoginResponse(
        access_token=tokens.get("AccessToken", ""),
        id_token=tokens.get("IdToken", ""),
        expires_in=int(tokens.get("ExpiresIn", "3600")),
        user=LoginUser(
            user_id=user_id,
            name=meta["display_name"],
            currency=meta["currency"],  # type: ignore[arg-type]
        ),
    )
    return response, tokens.get("RefreshToken", "")


def _read_user_meta(user_id: str) -> dict[str, str] | None:
    table = _table()
    response = table.get_item(Key={"PK": f"USER#{user_id}", "SK": "META"})
    item = response.get("Item")
    if not item:
        return None
    return {
        "display_name": str(item.get("display_name", "")),
        "currency": str(item.get("currency", "USD")),
    }


# ---- Refresh ---------------------------------------------------------


def refresh(refresh_token: str) -> RefreshResponse:
    if not refresh_token:
        raise AuthError(
            code="MISSING_REFRESH_TOKEN",
            http_status=401,
            message="Refresh token is missing.",
        )
    tokens = _cognito().initiate_auth_refresh(
        client_id=_web_client_id(),
        refresh_token=refresh_token,
    )
    return RefreshResponse(
        access_token=tokens.get("AccessToken", ""),
        id_token=tokens.get("IdToken", ""),
        expires_in=int(tokens.get("ExpiresIn", "3600")),
    )


# ---- Logout ----------------------------------------------------------


def logout(access_token: str) -> None:
    _cognito().global_sign_out(access_token=access_token)


# ---- Forgot password + reset -----------------------------------------


def forgot_password(req: ForgotPasswordRequest) -> None:
    """Initiate password reset; never leaks user existence."""
    rate_limit.consume_otp_email(req.email)
    try:
        _cognito().forgot_password(
            client_id=_web_client_id(),
            email=req.email,
        )
    except AuthError as e:
        if e.code == "USER_NOT_FOUND":
            return  # mask
        raise


def reset_password(req: ResetPasswordRequest) -> None:
    try:
        _cognito().confirm_forgot_password(
            client_id=_web_client_id(),
            email=req.email,
            code=req.code,
            password=req.new_password,
        )
    except AuthError as e:
        # Mask USER_NOT_FOUND on the reset path too — same rationale.
        if e.code == "USER_NOT_FOUND":
            raise AuthError(
                code="INVALID_CODE",
                http_status=401,
                message="The verification code is invalid or expired.",
            ) from e
        raise


# ---- Helpers ---------------------------------------------------------


def _utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
