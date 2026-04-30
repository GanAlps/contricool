"""Boto3 wrapper for Cognito User Pool calls.

Each method maps a Cognito ``ClientError`` to a stable
:class:`app.features.auth.errors.AuthError`. The client itself is
**silent** — handlers log ``{event, cognito_error_type}`` after the
exception bubbles up; this module never logs the email, password, or
the raw boto3 response.

Why not raise the boto3 exception subclasses (``client.exceptions.…``)
directly? Two reasons:

1. The set of exception classes is generated lazily per botocore
   client; matching by ``e.response["Error"]["Code"]`` is more robust
   across boto3 versions.
2. Path-dependent mapping: ``NotAuthorizedException`` is raised by
   Cognito on "wrong password" (login), "refresh token revoked"
   (refresh), and "access token revoked" (logout) — same exception,
   different correct HTTP status. The caller hint disambiguates.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

import boto3
from botocore.exceptions import ClientError

from app.features.auth.errors import AuthError

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp.client import CognitoIdentityProviderClient

# ---- Error code → AuthError factory map ------------------------------

# Codes that have a single deterministic HTTP mapping regardless of
# which Cognito call surfaced them.
_FIXED_MAP: Final[dict[str, tuple[str, int, str]]] = {
    "UsernameExistsException":
        ("EMAIL_EXISTS", 409, "An account with this email already exists."),
    "InvalidPasswordException":
        ("INVALID_PASSWORD", 422, "Password does not meet requirements."),
    "CodeMismatchException":
        ("INVALID_CODE", 401, "The verification code is invalid or expired."),
    "ExpiredCodeException":
        ("INVALID_CODE", 401, "The verification code is invalid or expired."),
    "UserNotConfirmedException":
        ("ACCOUNT_NOT_ACTIVE", 403, "Account email is not yet verified."),
    "PasswordResetRequiredException":
        ("PASSWORD_RESET_REQUIRED", 403, "Password reset is required."),
    "LimitExceededException":
        ("RATE_LIMITED", 429, "Too many attempts. Try again later."),
    "TooManyRequestsException":
        ("RATE_LIMITED", 429, "Too many attempts. Try again later."),
    "InvalidParameterException":
        # Cognito raises this for "user already confirmed" on resend,
        # plus a handful of generic 4xx misuses. We treat it as 409
        # ALREADY_CONFIRMED on the resend path; service-layer code may
        # remap if it fires elsewhere.
        ("ALREADY_CONFIRMED", 409, "Account is already confirmed."),
}


def _build_client() -> CognitoIdentityProviderClient:
    """Construct the boto3 cognito-idp client.

    Region comes from ``AWS_REGION`` (Lambda sets this automatically) or
    ``AWS_DEFAULT_REGION`` (tests + local dev). We avoid pulling from
    ``app.core.config`` so this module imports cleanly before
    ``config.load()`` runs — important for unit tests that exercise
    error mapping without touching SSM.
    """
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return boto3.client("cognito-idp", region_name=region)


_default_client: CognitoIdentityProviderClient | None = None


def _client() -> CognitoIdentityProviderClient:
    global _default_client
    if _default_client is None:
        _default_client = _build_client()
    return _default_client


def _set_client_for_tests(client: CognitoIdentityProviderClient | None) -> None:
    """Inject a custom cognito-idp client (e.g. a moto-backed one)."""
    global _default_client
    _default_client = client


def _normalise(email: str) -> str:
    return email.strip().lower()


def _path_aware_not_authorized(path: str) -> AuthError:
    """Map ``NotAuthorizedException`` to the right code per call site."""
    if path == "login":
        return AuthError(
            code="INVALID_CREDENTIALS",
            http_status=401,
            message="Email or password is incorrect.",
        )
    if path == "refresh":
        # Distinct from generic UNAUTHENTICATED so the SDK can route
        # "session expired" UX separately from "bad bearer token" —
        # see Design 4 R5.4 / Phase 2c spec N15.
        return AuthError(
            code="REFRESH_FAILED",
            http_status=401,
            message="Refresh token is invalid or expired.",
        )
    # logout / forgot / reset and generic
    return AuthError(
        code="UNAUTHENTICATED",
        http_status=401,
        message="Authentication required.",
    )


def _path_aware_user_not_found(path: str) -> AuthError:
    if path == "verify_email":
        return AuthError(
            code="USER_NOT_FOUND",
            http_status=404,
            message="No account exists for this email.",
        )
    if path == "login":
        # Mask: don't tell the attacker the email isn't registered.
        return AuthError(
            code="INVALID_CREDENTIALS",
            http_status=401,
            message="Email or password is incorrect.",
        )
    if path in ("forgot_password", "resend"):
        # Caller will translate to a 202 success response. We don't
        # raise here — but if it does bubble we mask too.
        return AuthError(
            code="USER_NOT_FOUND",
            http_status=404,
            message="No account exists for this email.",
        )
    return AuthError(
        code="USER_NOT_FOUND",
        http_status=404,
        message="No account exists for this email.",
    )


def _map_error(exc: ClientError, *, path: str) -> AuthError:
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "NotAuthorizedException":
        return _path_aware_not_authorized(path)
    if code == "UserNotFoundException":
        return _path_aware_user_not_found(path)
    if code in _FIXED_MAP:
        new_code, http_status, message = _FIXED_MAP[code]
        return AuthError(code=new_code, http_status=http_status, message=message)
    # Any other Cognito error is a server-side problem — don't leak
    # internals. Caller-side logger records ``cognito_error_type=code``.
    return AuthError(
        code="INTERNAL",
        http_status=500,
        message="An internal error occurred.",
    )


# ---- Public client surface ------------------------------------------


class CognitoClient:
    """Thin wrapper around boto3 cognito-idp with error mapping."""

    def __init__(self, *, user_pool_id: str) -> None:
        if not user_pool_id:
            raise ValueError("user_pool_id is required")
        self._user_pool_id = user_pool_id

    # ----- Sign up + verify -----

    def sign_up(
        self,
        *,
        client_id: str,
        email: str,
        password: str,
        attributes: dict[str, str],
    ) -> str:
        """Returns Cognito's ``UserSub`` UUID. Caller does NOT use it for
        identity — the project keys on ``custom:user_id`` (a server-
        generated ULID supplied via ``attributes``).
        """
        try:
            response = _client().sign_up(
                ClientId=client_id,
                Username=_normalise(email),
                Password=password,
                UserAttributes=[
                    {"Name": k, "Value": v} for k, v in attributes.items()
                ],
            )
        except ClientError as e:
            raise _map_error(e, path="signup") from e
        return str(response["UserSub"])

    def confirm_sign_up(self, *, client_id: str, email: str, code: str) -> None:
        try:
            _client().confirm_sign_up(
                ClientId=client_id,
                Username=_normalise(email),
                ConfirmationCode=code,
            )
        except ClientError as e:
            raise _map_error(e, path="verify_email") from e

    def admin_get_user(self, *, email: str) -> dict[str, str]:
        """Returns flat ``{attr_name: value, "Username": ...}`` dict."""
        try:
            response = _client().admin_get_user(
                UserPoolId=self._user_pool_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            raise _map_error(e, path="admin_get_user") from e
        out: dict[str, str] = {"Username": response["Username"]}
        for attr in response.get("UserAttributes", []):
            out[attr["Name"]] = attr["Value"]
        return out

    def resend_confirmation_code(self, *, client_id: str, email: str) -> None:
        try:
            _client().resend_confirmation_code(
                ClientId=client_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            raise _map_error(e, path="resend") from e

    # ----- Login + refresh + logout -----

    def initiate_auth_user_password(
        self, *, client_id: str, email: str, password: str
    ) -> dict[str, str]:
        """Returns ``{access_token, id_token, refresh_token, expires_in}``."""
        try:
            response = _client().initiate_auth(
                ClientId=client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": _normalise(email),
                    "PASSWORD": password,
                },
            )
        except ClientError as e:
            raise _map_error(e, path="login") from e
        return _extract_auth_result(response)

    def initiate_auth_refresh(
        self, *, client_id: str, refresh_token: str
    ) -> dict[str, str]:
        try:
            response = _client().initiate_auth(
                ClientId=client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
        except ClientError as e:
            raise _map_error(e, path="refresh") from e
        return _extract_auth_result(response)

    def global_sign_out(self, *, access_token: str) -> None:
        try:
            _client().global_sign_out(AccessToken=access_token)
        except ClientError as e:
            raise _map_error(e, path="logout") from e

    # ----- Admin lifecycle (Phase 7 — account deletion) -----

    def admin_disable_user(self, *, email: str) -> None:
        """Mark a Cognito user as disabled. Existing access tokens
        keep working until expiry (~1 h) but new ``InitiateAuth``
        attempts return ``NotAuthorizedException``.

        Idempotent: calling on an already-disabled user is a no-op
        and returns success. Tolerates ``UserNotFoundException`` so a
        late ``DELETE /v1/me`` after the cleanup Lambda has already
        removed the Cognito user still returns 204 (the user is gone
        in Cognito; that *is* the post-condition we want).
        """
        try:
            _client().admin_disable_user(
                UserPoolId=self._user_pool_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                return
            raise _map_error(e, path="admin_disable_user") from e

    def admin_user_global_sign_out(self, *, email: str) -> None:
        """Revoke every refresh token for a user. Pairs with
        ``admin_disable_user`` so a deactivated account can't ride
        an existing refresh token to keep working past disable.

        Tolerates ``UserNotFoundException`` for the same reason as
        ``admin_disable_user``.
        """
        try:
            _client().admin_user_global_sign_out(
                UserPoolId=self._user_pool_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                return
            raise _map_error(e, path="admin_user_global_sign_out") from e

    def admin_delete_user(self, *, email: str) -> None:
        """Permanently delete a Cognito user. Used by the cleanup
        Lambda 30 days after a deactivation.

        Tolerates ``UserNotFoundException`` — the cleanup Lambda
        is idempotent across retries.
        """
        try:
            _client().admin_delete_user(
                UserPoolId=self._user_pool_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "UserNotFoundException":
                return
            raise _map_error(e, path="admin_delete_user") from e

    # ----- Forgot password + reset -----

    def forgot_password(self, *, client_id: str, email: str) -> None:
        try:
            _client().forgot_password(
                ClientId=client_id,
                Username=_normalise(email),
            )
        except ClientError as e:
            err = _map_error(e, path="forgot_password")
            # forgot_password's "user not found" is masked at the route
            # layer (R7.4). We bubble the mapped error and let the
            # service decide.
            raise err from e

    def confirm_forgot_password(
        self, *, client_id: str, email: str, code: str, password: str
    ) -> None:
        try:
            _client().confirm_forgot_password(
                ClientId=client_id,
                Username=_normalise(email),
                ConfirmationCode=code,
                Password=password,
            )
        except ClientError as e:
            raise _map_error(e, path="reset_password") from e


def _extract_auth_result(response: object) -> dict[str, str]:
    if not isinstance(response, dict):
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        )
    auth = response.get("AuthenticationResult") or {}
    if not isinstance(auth, dict):
        raise AuthError(
            code="INTERNAL",
            http_status=500,
            message="An internal error occurred.",
        )
    out: dict[str, str] = {}
    for key in ("AccessToken", "IdToken", "RefreshToken", "ExpiresIn", "TokenType"):
        if key in auth:
            out[key] = str(auth[key])
    return out
