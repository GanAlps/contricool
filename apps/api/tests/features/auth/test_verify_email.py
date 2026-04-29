"""Tests for ``POST /v1/auth/verify-email``."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.features.auth.conftest import confirm_user

_SIGNUP = {
    "email": "alice@example.com",
    "password": "P@ssword123!",
    "name": "Alice",
    "currency": "USD",
}


def test_verify_email_unknown_email_404(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    r = auth_client.post(
        "/v1/auth/verify-email",
        json={"email": "ghost@example.com", "code": "123456"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


def test_verify_email_writes_meta_row(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Happy path — Cognito returns CONFIRMED, we write USER#<id>#META."""
    auth_client.post("/v1/auth/signup", json=_SIGNUP)

    # moto's confirm_sign_up accepts any code as a no-op success.
    r = auth_client.post(
        "/v1/auth/verify-email",
        json={"email": _SIGNUP["email"], "code": "123456"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email_verified"] is True
    assert body["account_active"] is True

    # META row exists, with the pending currency and email hash on GSI1.
    from app.core.lookup_hash import email_hash

    table = auth_env["table"]
    cognito = auth_env["cognito"]
    user_attrs = cognito.admin_get_user(  # type: ignore[attr-defined]
        UserPoolId=auth_env["pool_id"],
        Username=_SIGNUP["email"],
    )
    custom_user_id = next(
        a["Value"] for a in user_attrs["UserAttributes"] if a["Name"] == "custom:user_id"
    )
    item = table.get_item(  # type: ignore[attr-defined]
        Key={"PK": f"USER#{custom_user_id}", "SK": "META"}
    ).get("Item")
    assert item is not None
    assert item["display_name"] == "Alice"
    assert item["currency"] == "USD"
    assert item["status"] == "active"
    assert item["GSI1PK"] == f"EMAIL#{email_hash(_SIGNUP['email'])}"


def test_verify_email_idempotent_second_call_no_op(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """Calling verify-email twice returns 200 both times; META row written
    only once (the second PutItem is condition-rejected silently)."""
    auth_client.post("/v1/auth/signup", json=_SIGNUP)
    r1 = auth_client.post(
        "/v1/auth/verify-email", json={"email": _SIGNUP["email"], "code": "111111"}
    )
    r2 = auth_client.post(
        "/v1/auth/verify-email", json={"email": _SIGNUP["email"], "code": "111111"}
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_verify_email_extra_field_rejected(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/verify-email",
        json={"email": "a@b.com", "code": "123456", "evil": True},
    )
    assert r.status_code == 422


def test_verify_email_invalid_email_format_422(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/v1/auth/verify-email", json={"email": "not-an-email", "code": "123456"}
    )
    assert r.status_code == 422


# Synthetic test for the 500 path — triggered when Cognito succeeds but
# admin_get_user lacks ``custom:user_id`` (operational anomaly).
def test_verify_email_500_when_custom_user_id_missing(
    auth_client: TestClient,
    auth_env: dict[str, object],
    monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    auth_client.post("/v1/auth/signup", json=_SIGNUP)

    from app.features.auth import service

    real = service._cognito

    class _Wrap:
        def __init__(self, c: object) -> None:
            self._c = c

        def __getattr__(self, name: str) -> object:
            return getattr(self._c, name)

        def admin_get_user(self, *, email: str) -> dict[str, str]:
            return {"Username": email, "email": email, "name": "Alice"}

        def confirm_sign_up(self, **kwargs: object) -> None:
            return self._c.confirm_sign_up(**kwargs)  # type: ignore[union-attr]

    monkeypatch.setattr(service, "_cognito", lambda: _Wrap(real()))
    r = auth_client.post(
        "/v1/auth/verify-email", json={"email": _SIGNUP["email"], "code": "111111"}
    )
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"


def test_verify_email_ddb_failure_returns_500(
    auth_client: TestClient,
    auth_env: dict[str, object],
    monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    """If the META PutItem fails with anything other than the conditional
    check, return 500."""
    from botocore.exceptions import ClientError

    auth_client.post("/v1/auth/signup", json=_SIGNUP)
    table = auth_env["table"]
    real_put = table.put_item  # type: ignore[attr-defined]

    def _bad_put(**kwargs: object) -> object:
        if kwargs.get("ConditionExpression") == "attribute_not_exists(PK)":
            raise ClientError(
                error_response={
                    "Error": {"Code": "ResourceNotFoundException", "Message": "x"},
                    "ResponseMetadata": {},
                },
                operation_name="PutItem",
            )
        return real_put(**kwargs)

    monkeypatch.setattr(table, "put_item", _bad_put)
    r = auth_client.post(
        "/v1/auth/verify-email", json={"email": _SIGNUP["email"], "code": "111111"}
    )
    assert r.status_code == 500


def test_verify_email_default_currency_when_pending_missing(
    auth_client: TestClient, auth_env: dict[str, object]
) -> None:
    """If the EMAIL#<hash>#PENDING row doesn't exist (e.g. signup didn't
    write it because of a transient failure), verify-email writes the
    META row with currency=USD as the safe default."""
    # Simulate a Cognito user that was created without the matching
    # PENDING row (sign up via Cognito directly, bypass signup).
    cog = auth_env["cognito"]
    cog.admin_create_user(  # type: ignore[attr-defined]
        UserPoolId=auth_env["pool_id"],
        Username="orphan@example.com",
        UserAttributes=[
            {"Name": "email", "Value": "orphan@example.com"},
            {"Name": "name", "Value": "Orphan"},
            {"Name": "custom:user_id", "Value": "01HZZZZZZZZZZZZZZZZZZZZZZZ"},
        ],
        MessageAction="SUPPRESS",
    )
    confirm_user(auth_env, "orphan@example.com")
    r = auth_client.post(
        "/v1/auth/verify-email",
        json={"email": "orphan@example.com", "code": "999999"},
    )
    assert r.status_code == 200
    table = auth_env["table"]
    item = table.get_item(  # type: ignore[attr-defined]
        Key={"PK": "USER#01HZZZZZZZZZZZZZZZZZZZZZZZ", "SK": "META"}
    ).get("Item")
    assert item is not None
    assert item["currency"] == "USD"  # default


def test_pending_currency_invalid_falls_back_to_usd(
    auth_env: dict[str, object],
) -> None:
    """If somehow the pending row holds a currency outside ``USD/INR``,
    ``_read_pending_currency`` falls back to USD."""
    from app.core.lookup_hash import email_hash
    from app.features.auth.service import _read_pending_currency

    table = auth_env["table"]
    table.put_item(  # type: ignore[attr-defined]
        Item={
            "PK": f"EMAIL#{email_hash('weird@example.com')}",
            "SK": "PENDING",
            "currency": "EUR",
        }
    )
    assert _read_pending_currency("weird@example.com") == "USD"
