"""Tests for ``app.core.config.load`` against a moto SSM stub."""
from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from app.core import config


@pytest.fixture
def env_vars() -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in ("ENV_NAME", "AWS_REGION", "APP_VERSION")}
    os.environ["ENV_NAME"] = "dev"
    os.environ["AWS_REGION"] = "us-west-2"
    os.environ["APP_VERSION"] = "1.2.3-test"
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _seed_ssm(values: dict[str, str], *, env: str = "dev") -> None:
    ssm = boto3.client("ssm", region_name="us-west-2")
    base = {
        f"/contricool/{env}/cognito/user-pool-id": "us-west-2_DEVPOOL000",
        f"/contricool/{env}/cognito/client-id-web": "webclient000000000000000",
        f"/contricool/{env}/cognito/client-id-ios": "iosclient000000000000000",
        f"/contricool/{env}/cognito/client-id-android": "androidclient00000000000",
        f"/contricool/{env}/ddb/users-table-name": f"ContriCool-Users-{env}",
        f"/contricool/{env}/pii-salt": "deadbeef" * 8,  # 64-char hex
    }
    base.update(values)
    for name, value in base.items():
        ptype = "SecureString" if name.endswith("/pii-salt") else "String"
        ssm.put_parameter(Name=name, Value=value, Type=ptype, Overwrite=True)


@mock_aws
def test_load_returns_app_config(
    env_vars: None,
    aws_credentials: None,
) -> None:
    _seed_ssm({})

    cfg = config.load()

    assert cfg.env_name == "dev"
    assert cfg.aws_region == "us-west-2"
    assert cfg.app_version == "1.2.3-test"
    assert cfg.cognito_user_pool_id == "us-west-2_DEVPOOL000"
    assert cfg.cognito_web_client_id == "webclient000000000000000"
    assert cfg.cognito_ios_client_id == "iosclient000000000000000"
    assert cfg.cognito_android_client_id == "androidclient00000000000"
    assert cfg.users_table_name == "ContriCool-Users-dev"
    assert cfg.pii_salt == "deadbeef" * 8


@mock_aws
def test_load_caches_after_first_call(
    env_vars: None,
    aws_credentials: None,
) -> None:
    _seed_ssm({})
    first = config.load()
    # Subsequent call must short-circuit; we patch ``_build_from_ssm`` to
    # detect any further invocation.
    with patch.object(config, "_build_from_ssm") as build_again:
        second = config.load()
    assert second is first
    build_again.assert_not_called()


@mock_aws
def test_load_raises_on_missing_param(
    env_vars: None,
    aws_credentials: None,
) -> None:
    """A parameter that doesn't exist in SSM must surface as RuntimeError
    naming the missing key — not silently fall through."""
    # Seed only 5 of the 6 needed params (omit pii-salt).
    ssm = boto3.client("ssm", region_name="us-west-2")
    for name, value in {
        "/contricool/dev/cognito/user-pool-id": "x",
        "/contricool/dev/cognito/client-id-web": "x",
        "/contricool/dev/cognito/client-id-ios": "x",
        "/contricool/dev/cognito/client-id-android": "x",
        "/contricool/dev/ddb/users-table-name": "x",
    }.items():
        ssm.put_parameter(Name=name, Value=value, Type="String")

    with pytest.raises(RuntimeError, match="pii-salt"):
        config.load()


@mock_aws
def test_load_raises_on_empty_param(
    env_vars: None,
    aws_credentials: None,
) -> None:
    """An empty SSM value must NOT silently degrade to a default."""
    # SSM rejects truly-empty values; simulate by patching the response.
    _seed_ssm({})
    real_client = boto3.client
    fake_response = {
        "Parameters": [
            {"Name": "/contricool/dev/cognito/user-pool-id", "Value": ""},
            {"Name": "/contricool/dev/cognito/client-id-web", "Value": "x"},
            {"Name": "/contricool/dev/cognito/client-id-ios", "Value": "x"},
            {"Name": "/contricool/dev/cognito/client-id-android", "Value": "x"},
            {"Name": "/contricool/dev/ddb/users-table-name", "Value": "x"},
            {"Name": "/contricool/dev/pii-salt", "Value": "x"},
        ],
        "InvalidParameters": [],
    }

    class _StubSSM:
        def get_parameters(self, **_kwargs: object) -> dict[str, object]:
            return fake_response

    def _fake_client(name: str, **kw: object) -> object:
        if name == "ssm":
            return _StubSSM()
        return real_client(name, **kw)  # type: ignore[arg-type]

    with patch("app.core.config.boto3.client", side_effect=_fake_client):
        with pytest.raises(RuntimeError, match="empty"):
            config.load()


def test_load_raises_on_missing_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_NAME", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    with pytest.raises(RuntimeError, match="ENV_NAME"):
        config.load()


def test_set_for_tests_overrides_cache(seed_config: object) -> None:
    """The autouse reset fixture cleared the cache; ``seed_config`` puts
    a known value back. ``load()`` must return it without hitting SSM."""
    cfg = config.load()
    assert cfg.env_name == "test"
    assert cfg.users_table_name == "ContriCool-Users-test"


def test_set_for_tests_clears_cache_when_called_with_none() -> None:
    config._set_for_tests(None)
    assert config._cache is None


@mock_aws
def test_load_double_checked_locking(
    env_vars: None,
    aws_credentials: None,
) -> None:
    """When two threads race past the first ``_cache is None`` check, the
    second one wakes up inside the lock and must short-circuit. Simulate
    by patching ``_build_from_ssm`` to populate ``_cache`` itself."""
    _seed_ssm({})

    real_build = config._build_from_ssm

    def _build_and_cache_inside_lock() -> config.AppConfig:
        cfg = real_build()
        config._cache = cfg
        return cfg

    with patch.object(
        config, "_build_from_ssm", side_effect=_build_and_cache_inside_lock
    ) as build:
        first = config.load()
        # Second call goes through the same code path; _cache is already
        # set by the first call so neither check inside the lock triggers
        # _build_from_ssm.
        second = config.load()
    assert first is second
    assert build.call_count == 1


@mock_aws
def test_load_raises_when_ssm_returns_partial_response(
    env_vars: None,
    aws_credentials: None,
) -> None:
    """SSM returns success but omits a field's row entirely (no
    InvalidParameters either) — possible if read perms are partial."""
    real_client = boto3.client

    class _StubSSM:
        def get_parameters(self, **_kwargs: object) -> dict[str, object]:
            return {
                "Parameters": [
                    {"Name": "/contricool/dev/cognito/user-pool-id", "Value": "x"},
                    # All others omitted entirely.
                ],
                "InvalidParameters": [],
            }

    def _fake_client(name: str, **kw: object) -> object:
        if name == "ssm":
            return _StubSSM()
        return real_client(name, **kw)  # type: ignore[arg-type]

    with patch("app.core.config.boto3.client", side_effect=_fake_client):
        with pytest.raises(RuntimeError, match="no value for fields"):
            config.load()
