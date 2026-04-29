"""Tests for ``/v1/auth/forgot-password`` + ``/v1/auth/reset-password``."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.features.auth import cognito_client


def test_forgot_password_known_email_202(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Conftest's _WrappedCognito stubs forgot_password to no-op success."""
    auth_client.post(
        "/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "P@ssword123!",
            "name": "Alice",
            "currency": "USD",
        },
    )
    r = auth_client.post(
        "/v1/auth/forgot-password", json={"email": "alice@example.com"}
    )
    assert r.status_code == 202
    assert r.json()["status"] == "RESET_CODE_SENT"


def test_forgot_password_unknown_email_still_202(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """No-leak: unknown email returns 202 (R7.4)."""
    fake = MagicMock()
    from botocore.exceptions import ClientError

    def _err(**kwargs: object) -> None:
        raise ClientError(
            error_response={
                "Error": {"Code": "UserNotFoundException", "Message": "x"},
                "ResponseMetadata": {},
            },
            operation_name="ForgotPassword",
        )

    fake.forgot_password.side_effect = _err
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/forgot-password", json={"email": "ghost@example.com"}
        )
        assert r.status_code == 202
    finally:
        # Restore the conftest wrapper.
        from tests.features.auth.conftest import _WrappedCognito

        cognito_client._set_client_for_tests(_WrappedCognito(auth_env["cognito"]))  # type: ignore[arg-type]


def test_forgot_password_shares_rate_limit_with_resend(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """N25: 3 resend + 3 forgot in one hour share the OTP#EMAIL row →
    6th call (forgot) trips the cap."""
    email = "alice@example.com"
    auth_client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "P@ssword123!",
            "name": "Alice",
            "currency": "USD",
        },
    )
    for _ in range(3):
        assert (
            auth_client.post(
                "/v1/auth/resend-email-code", json={"email": email}
            ).status_code
            == 202
        )
    for _ in range(2):
        assert (
            auth_client.post(
                "/v1/auth/forgot-password", json={"email": email}
            ).status_code
            == 202
        )
    # 6th overall call → 429.
    r = auth_client.post(
        "/v1/auth/forgot-password", json={"email": email}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_forgot_password_extra_field_rejected(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/forgot-password", json={"email": "x@x.com", "evil": True}
    )
    assert r.status_code == 422


def test_forgot_password_propagates_non_user_not_found_errors(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Cognito errors other than USER_NOT_FOUND surface to the caller."""
    fake = MagicMock()
    from botocore.exceptions import ClientError

    fake.forgot_password.side_effect = ClientError(
        error_response={
            "Error": {"Code": "LimitExceededException", "Message": "x"},
            "ResponseMetadata": {},
        },
        operation_name="ForgotPassword",
    )
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/forgot-password", json={"email": "alice@example.com"}
        )
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "RATE_LIMITED"
    finally:
        from tests.features.auth.conftest import _WrappedCognito

        cognito_client._set_client_for_tests(_WrappedCognito(auth_env["cognito"]))  # type: ignore[arg-type]


# ---- Reset password ------------------------------------------------


def test_reset_password_happy(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Conftest's wrapper stubs confirm_forgot_password to success."""
    r = auth_client.post(
        "/v1/auth/reset-password",
        json={
            "email": "alice@example.com",
            "code": "123456",
            "new_password": "N3wPassw0rd!",
        },
    )
    assert r.status_code == 200
    assert r.json()["password_reset"] is True


def test_reset_password_wrong_code_401(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    fake = MagicMock()
    from botocore.exceptions import ClientError

    fake.confirm_forgot_password.side_effect = ClientError(
        error_response={
            "Error": {"Code": "CodeMismatchException", "Message": "x"},
            "ResponseMetadata": {},
        },
        operation_name="ConfirmForgotPassword",
    )
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/reset-password",
            json={
                "email": "alice@example.com",
                "code": "000000",
                "new_password": "N3wPassw0rd!",
            },
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CODE"
    finally:
        from tests.features.auth.conftest import _WrappedCognito

        cognito_client._set_client_for_tests(_WrappedCognito(auth_env["cognito"]))  # type: ignore[arg-type]


def test_reset_password_weak_password_422(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post(
        "/v1/auth/reset-password",
        json={
            "email": "x@x.com",
            "code": "123456",
            "new_password": "short",  # < 10 chars
        },
    )
    assert r.status_code == 422


def test_reset_password_unknown_email_masked_as_invalid_code(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    fake = MagicMock()
    from botocore.exceptions import ClientError

    fake.confirm_forgot_password.side_effect = ClientError(
        error_response={
            "Error": {"Code": "UserNotFoundException", "Message": "x"},
            "ResponseMetadata": {},
        },
        operation_name="ConfirmForgotPassword",
    )
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/reset-password",
            json={
                "email": "ghost@example.com",
                "code": "123456",
                "new_password": "N3wPassw0rd!",
            },
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CODE"
    finally:
        from tests.features.auth.conftest import _WrappedCognito

        cognito_client._set_client_for_tests(_WrappedCognito(auth_env["cognito"]))  # type: ignore[arg-type]


def test_reset_password_extra_field_rejected(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/reset-password",
        json={
            "email": "x@x.com",
            "code": "123456",
            "new_password": "N3wPassw0rd!",
            "evil": True,
        },
    )
    assert r.status_code == 422
