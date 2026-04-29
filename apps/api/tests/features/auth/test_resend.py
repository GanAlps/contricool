"""Tests for ``POST /v1/auth/resend-email-code``."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.features.auth import cognito_client


def test_resend_happy_path_202(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
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
        "/v1/auth/resend-email-code", json={"email": "alice@example.com"}
    )
    assert r.status_code == 202
    assert r.json()["status"] == "RESENT"


def test_resend_unknown_email_still_returns_202(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """No leak: unknown email is masked as success (R3.6)."""
    # moto doesn't implement resend_confirmation_code; install a mock
    # that mirrors AWS's USER_NOT_FOUND response for unknown emails.
    fake = MagicMock(wraps=auth_env["cognito"])
    from botocore.exceptions import ClientError

    def _resend(**kwargs: object) -> None:
        username = kwargs.get("Username", "")
        if "ghost" in str(username):
            raise ClientError(
                error_response={
                    "Error": {"Code": "UserNotFoundException", "Message": "x"},
                    "ResponseMetadata": {},
                },
                operation_name="ResendConfirmationCode",
            )

    fake.resend_confirmation_code.side_effect = _resend
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/resend-email-code", json={"email": "ghost@example.com"}
        )
        assert r.status_code == 202
    finally:
        cognito_client._set_client_for_tests(auth_env["cognito"])  # type: ignore[arg-type]


def test_resend_already_confirmed_returns_409(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    fake = MagicMock(wraps=auth_env["cognito"])
    from botocore.exceptions import ClientError

    fake.resend_confirmation_code.side_effect = ClientError(
        error_response={
            "Error": {"Code": "InvalidParameterException", "Message": "x"},
            "ResponseMetadata": {},
        },
        operation_name="ResendConfirmationCode",
    )
    cognito_client._set_client_for_tests(fake)
    try:
        r = auth_client.post(
            "/v1/auth/resend-email-code", json={"email": "x@x.com"}
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ALREADY_CONFIRMED"
    finally:
        cognito_client._set_client_for_tests(auth_env["cognito"])  # type: ignore[arg-type]


def test_resend_rate_limit_hit_returns_429_with_retry_after(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    auth_client.post(
        "/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "P@ssword123!",
            "name": "Alice",
            "currency": "USD",
        },
    )
    # 5 successful resends.
    for _ in range(5):
        assert (
            auth_client.post(
                "/v1/auth/resend-email-code", json={"email": "alice@example.com"}
            ).status_code
            == 202
        )
    # 6th hits the cap.
    r = auth_client.post(
        "/v1/auth/resend-email-code", json={"email": "alice@example.com"}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) > 0
    assert int(r.headers["Retry-After"]) <= 3600


def test_resend_extra_field_rejected(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/resend-email-code", json={"email": "x@x.com", "evil": True}
    )
    assert r.status_code == 422
