"""FastAPI router for ``/v1/auth/*``.

Routes adapt HTTP request/response and cookie wiring around the pure
service-layer functions in :mod:`app.features.auth.service`.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.core.dependencies import current_principal
from app.core.principal import Principal
from app.features.auth import service
from app.features.auth.errors import AuthError
from app.features.auth.models import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    ResendEmailCodeRequest,
    ResendEmailCodeResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.features.auth.rate_limit import RateLimitExceeded

# Refresh-token cookie attributes per Design 4 (R4.3, R5, R6.3).
_REFRESH_COOKIE_NAME = "rt"
_REFRESH_COOKIE_PATH = "/v1/auth"
_REFRESH_COOKIE_MAX_AGE = 30 * 86400  # 30 days

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
    )


def _rate_limited_to_auth_error(exc: RateLimitExceeded) -> AuthError:
    return AuthError(
        code="RATE_LIMITED",
        http_status=429,
        message="Too many requests. Try again later.",
        retry_after_seconds=exc.retry_after_seconds,
    )


# ---- Signup ----------------------------------------------------------


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED, response_model=SignupResponse)
async def signup(req: SignupRequest) -> SignupResponse:
    return service.signup_with_pending(req)


# ---- Verify email ---------------------------------------------------


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(req: VerifyEmailRequest) -> VerifyEmailResponse:
    return service.verify_email(req)


# ---- Resend email code ----------------------------------------------


@router.post(
    "/resend-email-code",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResendEmailCodeResponse,
)
async def resend_email_code(
    req: ResendEmailCodeRequest,
) -> ResendEmailCodeResponse:
    try:
        service.resend_email_code(req)
    except RateLimitExceeded as exc:
        raise _rate_limited_to_auth_error(exc) from exc
    return ResendEmailCodeResponse(status="RESENT")


# ---- Login ----------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response) -> LoginResponse:
    body, refresh_token = service.login(req)
    if refresh_token:
        _set_refresh_cookie(response, refresh_token)
    return body


# ---- Refresh -------------------------------------------------------


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    rt: str | None = Cookie(default=None),
) -> RefreshResponse:
    if not rt:
        raise AuthError(
            code="MISSING_REFRESH_TOKEN",
            http_status=401,
            message="Refresh token is missing.",
        )
    try:
        return service.refresh(rt)
    except AuthError as e:
        if e.http_status == 401:
            # Bad refresh — clear the dead cookie before re-raising.
            # Setting it on the route's ``response`` doesn't help when
            # we're about to raise; flag the AuthError so the handler
            # adds the clear-cookie header to its envelope.
            e.clear_refresh_cookie = True
        raise


# ---- Logout --------------------------------------------------------


_ACCESS_TOKEN_HEADER = "x-cognito-access-token"


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    request: Request,
    response: Response,
    _principal: Principal = Depends(current_principal),  # noqa: B008
) -> None:
    # ``Authorization: Bearer <id_token>`` provides the principal. Cognito
    # ``GlobalSignOut`` requires a real *access* token, which doesn't
    # carry the identity claims our ``Principal`` model needs — so the
    # access token rides in a separate header. We clear the refresh
    # cookie even if ``GlobalSignOut`` fails so a partial logout doesn't
    # leave a usable refresh token in the browser.
    access_token = request.headers.get(_ACCESS_TOKEN_HEADER, "").strip()
    if not access_token:
        # 400 (not 401) — the principal authenticated successfully; the
        # request itself is malformed. Distinct ``MISSING_ACCESS_TOKEN``
        # code so the SDK can surface "you sent the id token but forgot
        # the access token" without conflating it with auth failure.
        # ``clear_refresh_cookie=True`` so a partial logout doesn't leave
        # a usable refresh token in the browser.
        raise AuthError(
            code="MISSING_ACCESS_TOKEN",
            http_status=400,
            message="X-Cognito-Access-Token header is required for logout.",
            clear_refresh_cookie=True,
        )
    try:
        service.logout(access_token)
    finally:
        _clear_refresh_cookie(response)


# ---- Forgot + reset password ---------------------------------------


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ForgotPasswordResponse,
)
async def forgot_password(req: ForgotPasswordRequest) -> ForgotPasswordResponse:
    try:
        service.forgot_password(req)
    except RateLimitExceeded as exc:
        raise _rate_limited_to_auth_error(exc) from exc
    return ForgotPasswordResponse(status="RESET_CODE_SENT")


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(req: ResetPasswordRequest) -> ResetPasswordResponse:
    service.reset_password(req)
    return ResetPasswordResponse(password_reset=True)
