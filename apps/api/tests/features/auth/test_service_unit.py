"""Unit tests for ``app.features.auth.service`` paths not exercised
through the integration tests."""
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from app.core import config
from app.core.config import AppConfig
from app.features.auth import service as svc
from app.features.auth.errors import AuthError
from app.features.auth.models import ResetPasswordRequest


def test_table_lazy_init_under_moto(
    seed_config: AppConfig, aws_credentials: None
) -> None:
    """Exercise the lazy ``_table()`` cache-miss path."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-west-2")
        ddb.create_table(
            TableName=seed_config.users_table_name,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        svc._set_table_for_tests(None)
        try:
            built = svc._table()
            assert built.name == seed_config.users_table_name
            assert svc._table() is built
        finally:
            svc._set_table_for_tests(None)


def test_refresh_with_empty_token_raises_missing_refresh_token() -> None:
    """The service-level ``refresh()`` short-circuits empty input."""
    config._set_for_tests(
        AppConfig(
            env_name="test",
            aws_region="us-west-2",
            app_version="0",
            cognito_user_pool_id="us-west-2_XXX",
            cognito_web_client_id="x",
            cognito_ios_client_id="y",
            cognito_android_client_id="z",
            users_table_name="t",
            transactions_table_name="x",
            pii_salt="s",
        )
    )
    try:
        with pytest.raises(AuthError) as excinfo:
            svc.refresh("")
        assert excinfo.value.code == "MISSING_REFRESH_TOKEN"
    finally:
        config._set_for_tests(None)


def test_reset_password_propagates_non_user_not_found_errors(
    auth_env: dict[str, object],
) -> None:
    """Cognito errors other than UserNotFound bubble through unchanged."""
    from unittest.mock import MagicMock

    from botocore.exceptions import ClientError

    from app.features.auth import cognito_client

    fake = MagicMock()
    fake.confirm_forgot_password.side_effect = ClientError(
        error_response={
            "Error": {"Code": "InvalidPasswordException", "Message": "x"},
            "ResponseMetadata": {},
        },
        operation_name="ConfirmForgotPassword",
    )
    cognito_client._set_client_for_tests(fake)
    try:
        with pytest.raises(AuthError) as excinfo:
            svc.reset_password(
                ResetPasswordRequest(
                    email="alice@example.com",
                    code="123456",
                    new_password="P@ssword123!",
                )
            )
        assert excinfo.value.code == "INVALID_PASSWORD"
    finally:
        from tests.features.auth.conftest import _WrappedCognito

        cognito_client._set_client_for_tests(
            _WrappedCognito(auth_env["cognito"])  # type: ignore[arg-type]
        )
