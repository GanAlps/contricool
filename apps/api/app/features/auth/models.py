"""Pydantic v2 request + response models for the auth feature.

Every request model uses ``extra="forbid"`` so a typo'd field becomes a
422 ``VALIDATION_ERROR``, not a silently-ignored attacker payload.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Cognito's password policy — server-side check is intentionally loose
# (just the length floor); Cognito itself rejects on complexity and
# returns ``InvalidPasswordException`` which we map to 422.
_PASSWORD_MIN_LENGTH = 10
_PASSWORD_MAX_LENGTH = 256

_E164_PATTERN = r"^\+[1-9]\d{1,14}$"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- Signup -----------------------------------------------------------


class SignupRequest(_StrictModel):
    email: EmailStr
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)
    name: str = Field(min_length=1, max_length=128)
    currency: Literal["USD", "INR"]
    phone: str | None = Field(default=None, pattern=_E164_PATTERN)


class SignupResponse(BaseModel):
    user_id: str = Field(min_length=26, max_length=26)
    status: Literal["PENDING_VERIFICATION"]


# ---- Verify email ----------------------------------------------------


class VerifyEmailRequest(_StrictModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


class VerifyEmailResponse(BaseModel):
    email_verified: bool
    account_active: bool


# ---- Resend email code -----------------------------------------------


class ResendEmailCodeRequest(_StrictModel):
    email: EmailStr


class ResendEmailCodeResponse(BaseModel):
    status: Literal["RESENT"]


# ---- Login ------------------------------------------------------------


class LoginRequest(_StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX_LENGTH)


class LoginUser(BaseModel):
    user_id: str
    name: str
    currency: Literal["USD", "INR"]


class LoginResponse(BaseModel):
    access_token: str
    id_token: str
    expires_in: int
    user: LoginUser
    # Native callers (X-Client-Platform: native) receive the refresh
    # token in the body for storage in expo-secure-store; web callers
    # continue to receive it via HttpOnly Set-Cookie and this field is
    # ``None``. Returning it in body to web would be an XSS exfil
    # surface, so the route gates this on the header.
    refresh_token: str | None = None


# ---- Refresh ---------------------------------------------------------


class RefreshRequest(_StrictModel):
    # Optional body for native callers; web callers omit the body and
    # the route reads the ``rt`` HttpOnly cookie instead.
    refresh_token: str | None = None


class RefreshResponse(BaseModel):
    access_token: str
    id_token: str
    expires_in: int


# ---- Forgot + reset password -----------------------------------------


class ForgotPasswordRequest(_StrictModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    status: Literal["RESET_CODE_SENT"]


class ResetPasswordRequest(_StrictModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)


class ResetPasswordResponse(BaseModel):
    password_reset: bool
