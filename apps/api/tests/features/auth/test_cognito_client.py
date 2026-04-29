"""Tests for ``CognitoClient`` against ``moto[cognitoidp]``.

Covers happy paths for all 9 methods plus the error mapping for every
Cognito exception code listed in the auth-feature design.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from app.features.auth import cognito_client as cc
from app.features.auth.errors import AuthError


@pytest.fixture
def moto_cognito(aws_credentials: None) -> Iterator[dict[str, str]]:
    """Spin up a moto Cognito User Pool + matching app client.

    Yields ``{user_pool_id, client_id}`` for the test to use.
    """
    with mock_aws():
        client = boto3.client("cognito-idp", region_name="us-west-2")
        pool = client.create_user_pool(
            PoolName="contricool-test",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength": 10,
                    "RequireUppercase": True,
                    "RequireLowercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": True,
                }
            },
            AutoVerifiedAttributes=["email"],
            UsernameAttributes=["email"],
            Schema=[
                {"Name": "email", "AttributeDataType": "String", "Required": True},
                {"Name": "name", "AttributeDataType": "String", "Required": True},
                {
                    "Name": "user_id",
                    "AttributeDataType": "String",
                    "Mutable": False,
                    "DeveloperOnlyAttribute": False,
                    "StringAttributeConstraints": {"MinLength": "26", "MaxLength": "26"},
                },
            ],
        )
        user_pool_id = pool["UserPool"]["Id"]
        app_client = client.create_user_pool_client(
            UserPoolId=user_pool_id,
            ClientName="web",
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
            GenerateSecret=False,
        )
        client_id = app_client["UserPoolClient"]["ClientId"]

        cc._set_client_for_tests(client)
        try:
            yield {"user_pool_id": user_pool_id, "client_id": client_id}
        finally:
            cc._set_client_for_tests(None)


@pytest.fixture
def cognito(moto_cognito: dict[str, str]) -> cc.CognitoClient:
    return cc.CognitoClient(user_pool_id=moto_cognito["user_pool_id"])


def _signup(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str], email: str = "alice@example.com"
) -> str:
    return cognito.sign_up(
        client_id=moto_cognito["client_id"],
        email=email,
        password="P@ssword123!",
        attributes={
            "email": email,
            "name": "Alice",
            "custom:user_id": "01HK3W7QF6VMYG8XR3DQ7B5N6P",
        },
    )


# ---- Constructor -------------------------------------------------------


def test_constructor_rejects_empty_pool() -> None:
    with pytest.raises(ValueError):
        cc.CognitoClient(user_pool_id="")


# ---- sign_up ----------------------------------------------------------


def test_sign_up_returns_user_sub(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    sub = _signup(cognito, moto_cognito)
    assert isinstance(sub, str) and sub


def test_sign_up_normalises_email_case(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    sub1 = _signup(cognito, moto_cognito, email="Bob@Example.COM")
    # A second signup with the same lower-cased email should collide.
    with pytest.raises(AuthError) as excinfo:
        _signup(cognito, moto_cognito, email="bob@example.com")
    assert excinfo.value.code == "EMAIL_EXISTS"
    assert excinfo.value.http_status == 409
    assert sub1


def test_sign_up_invalid_password_maps_to_422(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.sign_up(
            client_id=moto_cognito["client_id"],
            email="weak@example.com",
            password="short",
            attributes={
                "email": "weak@example.com",
                "name": "Weak",
                "custom:user_id": "01HK3W7QF6VMYG8XR3DQ7B5N6P",
            },
        )
    assert excinfo.value.code == "INVALID_PASSWORD"
    assert excinfo.value.http_status == 422


# ---- confirm_sign_up + admin_get_user --------------------------------


def test_confirm_sign_up_unknown_email_maps_to_404(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.confirm_sign_up(
            client_id=moto_cognito["client_id"],
            email="ghost@example.com",
            code="123456",
        )
    assert excinfo.value.code == "USER_NOT_FOUND"
    assert excinfo.value.http_status == 404


def test_admin_get_user_returns_attributes(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    _signup(cognito, moto_cognito)
    boto3.client("cognito-idp", region_name="us-west-2").admin_confirm_sign_up(
        UserPoolId=moto_cognito["user_pool_id"], Username="alice@example.com"
    )
    attrs = cognito.admin_get_user(email="alice@example.com")
    assert attrs["email"] == "alice@example.com"
    assert attrs["name"] == "Alice"
    assert attrs["custom:user_id"] == "01HK3W7QF6VMYG8XR3DQ7B5N6P"


def test_admin_get_user_unknown_maps_to_404(
    cognito: cc.CognitoClient, _moto_cognito: dict[str, str] | None = None
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.admin_get_user(email="ghost@example.com")
    assert excinfo.value.code == "USER_NOT_FOUND"
    assert excinfo.value.http_status == 404


# ---- resend_confirmation_code (moto doesn't implement; use mocks) ----


def test_resend_confirmation_code_calls_underlying_client() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        client.resend_confirmation_code(client_id="cli", email="A@B.com")
        fake.resend_confirmation_code.assert_called_once_with(
            ClientId="cli", Username="a@b.com"
        )
    finally:
        cc._set_client_for_tests(None)


def test_resend_confirmation_code_already_confirmed_maps() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.resend_confirmation_code.side_effect = _make_client_error(
        "InvalidParameterException"
    )
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        with pytest.raises(AuthError) as excinfo:
            client.resend_confirmation_code(client_id="cli", email="a@b.com")
        assert excinfo.value.code == "ALREADY_CONFIRMED"
    finally:
        cc._set_client_for_tests(None)


# ---- confirm_forgot_password (moto auto-accepts; mock for negatives) -


def test_confirm_forgot_password_happy_via_mock() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        client.confirm_forgot_password(
            client_id="cli", email="a@b.com", code="123456", password="P@ssword123!"
        )
        fake.confirm_forgot_password.assert_called_once_with(
            ClientId="cli",
            Username="a@b.com",
            ConfirmationCode="123456",
            Password="P@ssword123!",
        )
    finally:
        cc._set_client_for_tests(None)


def test_confirm_forgot_password_wrong_code_via_mock() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.confirm_forgot_password.side_effect = _make_client_error("CodeMismatchException")
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        with pytest.raises(AuthError) as excinfo:
            client.confirm_forgot_password(
                client_id="cli", email="a@b.com", code="000000", password="P@ssword123!"
            )
        assert excinfo.value.code == "INVALID_CODE"
    finally:
        cc._set_client_for_tests(None)


# ---- global_sign_out happy path (moto's behavior varies) -------------


def test_global_sign_out_happy_via_mock() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        client.global_sign_out(access_token="some-access-token")
        fake.global_sign_out.assert_called_once_with(AccessToken="some-access-token")
    finally:
        cc._set_client_for_tests(None)


# ---- initiate_auth (login) -------------------------------------------


def _confirm_user(moto_cognito: dict[str, str], email: str) -> None:
    boto3.client("cognito-idp", region_name="us-west-2").admin_confirm_sign_up(
        UserPoolId=moto_cognito["user_pool_id"], Username=email
    )


def test_login_happy_path_returns_tokens(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    _signup(cognito, moto_cognito)
    _confirm_user(moto_cognito, "alice@example.com")
    result = cognito.initiate_auth_user_password(
        client_id=moto_cognito["client_id"],
        email="alice@example.com",
        password="P@ssword123!",
    )
    assert "AccessToken" in result
    assert "IdToken" in result
    assert "RefreshToken" in result


def test_login_wrong_password_maps_to_invalid_credentials(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    _signup(cognito, moto_cognito)
    _confirm_user(moto_cognito, "alice@example.com")
    with pytest.raises(AuthError) as excinfo:
        cognito.initiate_auth_user_password(
            client_id=moto_cognito["client_id"],
            email="alice@example.com",
            password="WrongPassw0rd!",
        )
    assert excinfo.value.code == "INVALID_CREDENTIALS"
    assert excinfo.value.http_status == 401


def test_login_unknown_email_masks_as_invalid_credentials(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.initiate_auth_user_password(
            client_id=moto_cognito["client_id"],
            email="ghost@example.com",
            password="anything",
        )
    assert excinfo.value.code == "INVALID_CREDENTIALS"


def test_login_unconfirmed_returns_account_not_active(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    _signup(cognito, moto_cognito, email="pending@example.com")
    # Don't confirm.
    with pytest.raises(AuthError) as excinfo:
        cognito.initiate_auth_user_password(
            client_id=moto_cognito["client_id"],
            email="pending@example.com",
            password="P@ssword123!",
        )
    assert excinfo.value.code == "ACCOUNT_NOT_ACTIVE"
    assert excinfo.value.http_status == 403


# ---- initiate_auth (refresh) -----------------------------------------


def test_refresh_with_bad_token_maps_to_refresh_failed(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.initiate_auth_refresh(
            client_id=moto_cognito["client_id"],
            refresh_token="not-a-real-refresh-token",
        )
    # moto raises NotAuthorizedException; per Spec R5.4 / N15 the
    # refresh path maps to REFRESH_FAILED so SDK clients can route
    # "session expired" UX separately from generic 401 UNAUTHENTICATED.
    assert excinfo.value.code == "REFRESH_FAILED"
    assert excinfo.value.http_status == 401


def test_refresh_happy_path_via_mock() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "new-a",
            "IdToken": "new-i",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        result = client.initiate_auth_refresh(client_id="cli", refresh_token="rt")
        assert result["AccessToken"] == "new-a"
        assert result["IdToken"] == "new-i"
    finally:
        cc._set_client_for_tests(None)


def test_forgot_password_user_not_found_via_mock() -> None:
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.forgot_password.side_effect = _make_client_error("UserNotFoundException")
    cc._set_client_for_tests(fake)
    try:
        client = cc.CognitoClient(user_pool_id="us-west-2_FAKEPOOL")
        with pytest.raises(AuthError) as excinfo:
            client.forgot_password(client_id="cli", email="ghost@example.com")
        # Service layer (R7.4) masks this to 202; we just verify the
        # mapped error bubbles correctly.
        assert excinfo.value.code == "USER_NOT_FOUND"
    finally:
        cc._set_client_for_tests(None)


# ---- global_sign_out -------------------------------------------------


def test_global_sign_out_with_invalid_token_maps_to_unauthenticated(
    cognito: cc.CognitoClient,
) -> None:
    with pytest.raises(AuthError) as excinfo:
        cognito.global_sign_out(access_token="not-a-real-access-token")
    assert excinfo.value.code == "UNAUTHENTICATED"


# ---- forgot_password / confirm_forgot_password -----------------------


def test_forgot_password_happy(
    cognito: cc.CognitoClient, moto_cognito: dict[str, str]
) -> None:
    _signup(cognito, moto_cognito)
    _confirm_user(moto_cognito, "alice@example.com")
    cognito.forgot_password(
        client_id=moto_cognito["client_id"], email="alice@example.com"
    )




# ---- _path_aware error mapping (synthetic ClientErrors) --------------


def _make_client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "msg"}, "ResponseMetadata": {}},
        operation_name="SignUp",
    )


@pytest.mark.parametrize(
    ("err_code", "expected_code", "expected_status"),
    [
        ("UsernameExistsException", "EMAIL_EXISTS", 409),
        ("InvalidPasswordException", "INVALID_PASSWORD", 422),
        ("CodeMismatchException", "INVALID_CODE", 401),
        ("ExpiredCodeException", "INVALID_CODE", 401),
        ("UserNotConfirmedException", "ACCOUNT_NOT_ACTIVE", 403),
        ("PasswordResetRequiredException", "PASSWORD_RESET_REQUIRED", 403),
        ("LimitExceededException", "RATE_LIMITED", 429),
        ("TooManyRequestsException", "RATE_LIMITED", 429),
        ("InvalidParameterException", "ALREADY_CONFIRMED", 409),
    ],
)
def test_fixed_map(err_code: str, expected_code: str, expected_status: int) -> None:
    err = cc._map_error(_make_client_error(err_code), path="signup")
    assert err.code == expected_code
    assert err.http_status == expected_status


def test_not_authorized_login_path_maps_to_invalid_credentials() -> None:
    err = cc._map_error(_make_client_error("NotAuthorizedException"), path="login")
    assert err.code == "INVALID_CREDENTIALS"


def test_not_authorized_refresh_path_maps_to_refresh_failed() -> None:
    """Spec R5.4 / N15: refresh path needs its own error code so SDK
    can distinguish from generic 401 UNAUTHENTICATED."""
    err = cc._map_error(_make_client_error("NotAuthorizedException"), path="refresh")
    assert err.code == "REFRESH_FAILED"
    assert err.http_status == 401


def test_not_authorized_logout_path_still_maps_to_unauthenticated() -> None:
    """Logout / forgot / reset retain UNAUTHENTICATED — only refresh
    branches off."""
    err = cc._map_error(_make_client_error("NotAuthorizedException"), path="logout")
    assert err.code == "UNAUTHENTICATED"


def test_user_not_found_login_path_masks_as_invalid_credentials() -> None:
    err = cc._map_error(_make_client_error("UserNotFoundException"), path="login")
    assert err.code == "INVALID_CREDENTIALS"


def test_user_not_found_verify_path_returns_user_not_found() -> None:
    err = cc._map_error(_make_client_error("UserNotFoundException"), path="verify_email")
    assert err.code == "USER_NOT_FOUND"
    assert err.http_status == 404


def test_user_not_found_forgot_path_returns_user_not_found() -> None:
    err = cc._map_error(_make_client_error("UserNotFoundException"), path="forgot_password")
    assert err.code == "USER_NOT_FOUND"


def test_user_not_found_unknown_path_falls_through_to_404() -> None:
    err = cc._map_error(_make_client_error("UserNotFoundException"), path="something_else")
    assert err.code == "USER_NOT_FOUND"


def test_unknown_error_code_maps_to_internal() -> None:
    err = cc._map_error(_make_client_error("SomeWildException"), path="signup")
    assert err.code == "INTERNAL"
    assert err.http_status == 500


# ---- _build_client + region selection --------------------------------


def test_build_client_uses_aws_region(
    aws_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    c = cc._build_client()
    assert c.meta.region_name == "ap-south-1"


def test_build_client_falls_back_to_default(
    aws_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    c = cc._build_client()
    assert c.meta.region_name == "us-west-2"


def test_module_client_singleton(aws_credentials: None) -> None:
    cc._set_client_for_tests(None)
    c1 = cc._client()
    c2 = cc._client()
    assert c1 is c2
    cc._set_client_for_tests(None)


def test_extract_auth_result_handles_missing_block() -> None:
    """Defensive — Cognito should always return AuthenticationResult on
    success, but we treat malformed responses as 500 rather than KeyError.
    """
    with pytest.raises(AuthError) as excinfo:
        cc._extract_auth_result({"AuthenticationResult": "not a dict"})
    assert excinfo.value.code == "INTERNAL"


def test_extract_auth_result_rejects_non_dict_response() -> None:
    with pytest.raises(AuthError) as excinfo:
        cc._extract_auth_result("not even a dict")
    assert excinfo.value.code == "INTERNAL"


def test_extract_auth_result_extracts_known_fields() -> None:
    out = cc._extract_auth_result(
        {
            "AuthenticationResult": {
                "AccessToken": "a",
                "IdToken": "i",
                "RefreshToken": "r",
                "ExpiresIn": 3600,
                "TokenType": "Bearer",
                "ExtraField": "ignored",
            }
        }
    )
    assert out == {
        "AccessToken": "a",
        "IdToken": "i",
        "RefreshToken": "r",
        "ExpiresIn": "3600",
        "TokenType": "Bearer",
    }


# ---- Test fixture sanity check ---------------------------------------


def test_aws_credentials_fixture_runs(aws_credentials: None) -> None:
    import os

    assert os.environ["AWS_ACCESS_KEY_ID"] == "testing"


def _suppress_unused(_: Any) -> None: ...
