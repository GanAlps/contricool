"""Shared pytest fixtures for the API test suite.

The Lambda runtime in production reads SSM at cold start; tests must NOT
hit AWS, so every fixture that needs config goes through
``app.core.config._set_for_tests`` with a deterministic ``AppConfig``.
"""
from __future__ import annotations

import os

# Set BEFORE any ``app.main`` import — ``app.main`` builds its module-level
# FastAPI instance at import time, which would otherwise call
# ``config.load()`` and fail in tests without an SSM stub.
os.environ.setdefault("CONTRICOOL_SKIP_COLD_START_CONFIG", "1")

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config
from app.core.config import AppConfig

_DEFAULT_TEST_CONFIG = AppConfig(
    env_name="test",
    aws_region="us-west-2",
    app_version="0.0.1-test",
    cognito_user_pool_id="us-west-2_TESTPOOL00",
    cognito_web_client_id="webclienttest00000000000",
    cognito_ios_client_id="iosclienttest00000000000",
    cognito_android_client_id="androidclienttest0000000",
    users_table_name="ContriCool-Users-test",
    pii_salt="test-salt-for-deterministic-hashes",
)


@pytest.fixture(autouse=True)
def _reset_config_cache() -> Iterator[None]:
    """Ensure each test starts with a clean config cache."""
    config._set_for_tests(None)
    yield
    config._set_for_tests(None)


@pytest.fixture
def seed_config() -> AppConfig:
    """Install a known-good ``AppConfig`` and return it."""
    config._set_for_tests(_DEFAULT_TEST_CONFIG)
    return _DEFAULT_TEST_CONFIG


@pytest.fixture
def app(seed_config: AppConfig) -> FastAPI:
    """Build a fresh FastAPI app per test, with the seeded config in place."""
    from app.main import create_app

    return create_app(load_config=False)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def aws_credentials() -> Iterator[None]:
    """Block real AWS calls — moto needs only the region and dummy creds."""
    saved = {
        k: os.environ.get(k)
        for k in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION",
        )
    }
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
