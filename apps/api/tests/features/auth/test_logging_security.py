"""Negative-test class N29/N30: PII redaction in auth-feature logs.

Red line 3 in CLAUDE.md mandates these for every auth-touching change:
no log line emitted by any auth endpoint may contain the request body's
``email``, ``password``, ``phone``, ``code``, ``new_password``, or any
JWT / refresh token. The Powertools ``RedactingFormatter`` (Phase 2b)
plus our handlers' deliberate exclusion of those keys from
``logger.extra=`` enforces this; this file proves it.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

_SECRETS = {
    "leaked_email": "topsecret_email_alice@example.com",
    "leaked_password": "P@sswordSecretValue123!",
    "leaked_phone": "+15558675309",
    "leaked_code": "987654",
    "leaked_new_password": "N3wPasswordZZZ!",
}


def _signup_body() -> dict[str, str]:
    return {
        "email": _SECRETS["leaked_email"],
        "password": _SECRETS["leaked_password"],
        "name": "Alice",
        "currency": "USD",
        "phone": _SECRETS["leaked_phone"],
    }


def _assert_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    text = "\n".join(
        rec.getMessage() + " " + str(rec.__dict__) for rec in caplog.records
    )
    for label, value in _SECRETS.items():
        assert value not in text, f"{label!r} value leaked into logs: {text!r}"


def test_signup_does_not_log_email_password_or_phone(
    auth_client: TestClient,
    auth_env: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="contricool-api")
    auth_client.post("/v1/auth/signup", json=_signup_body())
    _assert_no_secrets(caplog)


def test_verify_email_does_not_log_email_or_code(
    auth_client: TestClient,
    auth_env: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    auth_client.post("/v1/auth/signup", json=_signup_body())
    caplog.clear()
    caplog.set_level(logging.DEBUG, logger="contricool-api")
    auth_client.post(
        "/v1/auth/verify-email",
        json={
            "email": _SECRETS["leaked_email"],
            "code": _SECRETS["leaked_code"],
        },
    )
    _assert_no_secrets(caplog)


def test_login_does_not_log_password_or_tokens(
    auth_client: TestClient,
    auth_env: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from tests.features.auth.conftest import confirm_user

    auth_client.post("/v1/auth/signup", json=_signup_body())
    confirm_user(auth_env, _SECRETS["leaked_email"])
    auth_client.post(
        "/v1/auth/verify-email",
        json={"email": _SECRETS["leaked_email"], "code": "111111"},
    )
    caplog.clear()
    caplog.set_level(logging.DEBUG, logger="contricool-api")
    response = auth_client.post(
        "/v1/auth/login",
        json={
            "email": _SECRETS["leaked_email"],
            "password": _SECRETS["leaked_password"],
        },
    )
    # The fixture confirmed the user and wrote the META row, so login
    # is expected to succeed. Asserting 200 explicitly removes the
    # silent escape hatch where a non-200 would skip the leak check.
    assert response.status_code == 200, (
        f"login expected to succeed; got {response.status_code} "
        f"body={response.text!r}"
    )
    leaked_token = response.json()["access_token"]
    text = "\n".join(
        rec.getMessage() + " " + str(rec.__dict__) for rec in caplog.records
    )
    assert leaked_token not in text, "access_token leaked into logs"
    _assert_no_secrets(caplog)


def test_reset_password_does_not_log_code_or_new_password(
    auth_client: TestClient,
    auth_env: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="contricool-api")
    auth_client.post(
        "/v1/auth/reset-password",
        json={
            "email": _SECRETS["leaked_email"],
            "code": _SECRETS["leaked_code"],
            "new_password": _SECRETS["leaked_new_password"],
        },
    )
    _assert_no_secrets(caplog)
