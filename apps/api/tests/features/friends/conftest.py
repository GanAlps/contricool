"""Shared fixtures for friends-feature integration tests.

Spins up moto for cognito-idp + dynamodb, creates the Users table
**with GSI1** (the friends list-merge needs it), seeds an
``AppConfig``, and wires the feature-module table references.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.core import config
from app.core.config import AppConfig
from app.features.auth import cognito_client
from app.features.auth import rate_limit as auth_rl
from app.features.auth import service as auth_svc
from app.features.friends import rate_limit as friends_rl
from app.features.friends import repository as friends_repo


def _create_users_table_with_gsi1(ddb: Any, name: str) -> Any:
    return ddb.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def friends_env(aws_credentials: None) -> Iterator[dict[str, object]]:
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
        _create_users_table_with_gsi1(ddb, "ContriCool-Users-test")
        users_table = ddb.Table("ContriCool-Users-test")

        cfg = AppConfig(
            env_name="test",
            aws_region="us-west-2",
            app_version="0.0.1-test",
            cognito_user_pool_id=pool_id,
            cognito_web_client_id=client_id,
            cognito_ios_client_id=client_id,
            cognito_android_client_id=client_id,
            users_table_name="ContriCool-Users-test",
            pii_salt="test-salt-deterministic",
        )
        config._set_for_tests(cfg)
        cognito_client._set_client_for_tests(cog)  # type: ignore[arg-type]
        auth_rl._set_table_for_tests(users_table)
        auth_svc._set_table_for_tests(users_table)
        friends_repo._set_table_for_tests(users_table)
        friends_rl._set_table_for_tests(users_table)

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
            auth_rl._set_table_for_tests(None)
            auth_svc._set_table_for_tests(None)
            friends_repo._set_table_for_tests(None)
            friends_rl._set_table_for_tests(None)


def seed_user(
    env: dict[str, object],
    *,
    user_id: str,
    email: str,
    name: str,
    currency: str = "USD",
) -> None:
    """Write a META row + the GSI1 EMAIL-projection so lookups hit."""
    from app.core.lookup_hash import email_hash

    table = env["table"]
    table.put_item(  # type: ignore[attr-defined]
        Item={
            "PK": f"USER#{user_id}",
            "SK": "META",
            "GSI1PK": f"EMAIL#{email_hash(email)}",
            "GSI1SK": "USER",
            "display_name": name,
            "currency": currency,
            "status": "active",
            "created_at": _now_iso(),
        }
    )


def _now_iso() -> str:
    iso = datetime.now(UTC).replace(microsecond=0).isoformat()
    return iso.replace("+00:00", "Z")


def seed_friendship(
    env: dict[str, object], *, a_id: str, b_id: str, created_by: str | None = None
) -> None:
    """Write a canonical-pair friendship row (test helper)."""
    table = env["table"]
    min_id, max_id = (a_id, b_id) if a_id < b_id else (b_id, a_id)
    now = _now_iso()
    table.put_item(  # type: ignore[attr-defined]
        Item={
            "PK": f"USER#{min_id}",
            "SK": f"FRIEND#{max_id}",
            "GSI1PK": f"USER#{max_id}",
            "GSI1SK": f"FRIEND#{min_id}",
            "created_by": created_by or a_id,
            "created_at": now,
        }
    )


@pytest.fixture
def friends_client(friends_env: dict[str, object]) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app(load_config=False)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
