"""Shared fixtures for auth-feature integration tests.

Spins up moto for cognito-idp + dynamodb, creates a User Pool with one
app client + the Users table, wires the auth-feature module-scope
clients to point at the moto fakes, seeds an ``AppConfig`` matching
those IDs, and yields a ``TestClient`` already configured.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.core import config
from app.core.config import AppConfig
from app.features.auth import cognito_client
from app.features.auth import rate_limit as rl
from app.features.auth import service as svc


class _WrappedCognito:
    """Moto delegate that stubs the methods moto doesn't implement.

    moto 5.x has gaps for ``resend_confirmation_code``,
    ``forgot_password``, and ``confirm_forgot_password`` on Cognito.
    The auth feature still needs to exercise these paths in tests, so
    this wrapper returns benign success responses for the missing
    methods and forwards everything else to the real moto client.
    """

    _STUBBED_METHODS = frozenset({
        "resend_confirmation_code",
        "forgot_password",
        "confirm_forgot_password",
        "global_sign_out",
    })

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        if name in self._STUBBED_METHODS:
            return lambda **_kwargs: None
        return getattr(self._real, name)


@pytest.fixture
def auth_env(aws_credentials: None) -> Iterator[dict[str, object]]:
    with ExitStack() as stack:
        stack.enter_context(mock_aws())

        cog = boto3.client("cognito-idp", region_name="us-west-2")
        pool = cog.create_user_pool(
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
        pool_id = pool["UserPool"]["Id"]
        client = cog.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="web",
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
            GenerateSecret=False,
        )
        client_id = client["UserPoolClient"]["ClientId"]

        ddb = boto3.resource("dynamodb", region_name="us-west-2")
        ddb.create_table(
            TableName="ContriCool-Users-test",
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
        users_table = ddb.Table("ContriCool-Users-test")

        # Build an AppConfig with the moto pool/client/table IDs.
        cfg = AppConfig(
            env_name="test",
            aws_region="us-west-2",
            app_version="0.0.1-test",
            cognito_user_pool_id=pool_id,
            cognito_web_client_id=client_id,
            cognito_ios_client_id=client_id,  # MVP: same ID across platforms in test
            cognito_android_client_id=client_id,
            users_table_name="ContriCool-Users-test",
            transactions_table_name="ContriCool-Transactions-test",
            pii_salt="test-salt-for-deterministic-hashes",
        )
        config._set_for_tests(cfg)
        # Wrap the moto cognito client to stub out methods moto doesn't
        # implement (resend_confirmation_code, confirm_forgot_password,
        # forgot_password) — return None for happy-path; tests that
        # need error paths re-install a MagicMock.
        wrapped = _WrappedCognito(cog)
        cognito_client._set_client_for_tests(wrapped)  # type: ignore[arg-type]
        rl._set_table_for_tests(users_table)
        svc._set_table_for_tests(users_table)

        try:
            yield {
                "pool_id": pool_id,
                "client_id": client_id,
                "cognito": cog,
                "table": users_table,
                "config": cfg,
            }
        finally:
            cognito_client._set_client_for_tests(None)
            rl._set_table_for_tests(None)
            svc._set_table_for_tests(None)


@pytest.fixture
def auth_client(auth_env: dict[str, object]) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app(load_config=False)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def confirm_user(env: dict[str, object], email: str) -> None:
    """Server-side mark a Cognito user as confirmed (skip the email flow)."""
    cog = env["cognito"]
    cog.admin_confirm_sign_up(  # type: ignore[attr-defined]
        UserPoolId=env["pool_id"], Username=email
    )


def cognito_login(env: dict[str, object], email: str, password: str) -> dict[str, str]:
    """Helper: return real Cognito-issued tokens for tests that need them."""
    cog = env["cognito"]
    response = cog.initiate_auth(  # type: ignore[attr-defined]
        ClientId=env["client_id"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )
    return response["AuthenticationResult"]
