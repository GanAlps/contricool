"""Tests for the ``create_app`` factory + module-level app build path."""
from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppConfig


def test_create_app_returns_fastapi_with_health_route(
    seed_config: AppConfig,
) -> None:
    from app.main import create_app

    api = create_app(load_config=False)
    assert isinstance(api, FastAPI)
    with TestClient(api) as c:
        response = c.get("/v1/health")
    assert response.status_code == 200


def test_create_app_skips_ssm_when_load_config_false(
    seed_config: AppConfig,
) -> None:
    """The whole point of the ``load_config`` flag — tests must be able
    to build apps without hitting AWS."""
    from app.main import create_app

    # No SSM is mocked; if create_app(load_config=False) tried to call
    # boto3 here it would fail. Success means it didn't.
    api = create_app(load_config=False)
    assert api is not None


def test_module_app_built_with_skip_env_var(
    seed_config: AppConfig,
) -> None:
    """``CONTRICOOL_SKIP_COLD_START_CONFIG=1`` is set by ``conftest.py``
    so importing ``app.main`` doesn't try to load SSM. Re-importing here
    exercises the build path."""
    import app.main as main_mod

    importlib.reload(main_mod)
    assert isinstance(main_mod.app, FastAPI)


def test_create_app_with_load_config_uses_cached_config(
    seed_config: AppConfig,
) -> None:
    """When ``load_config=True`` and the cache is already populated
    (via ``seed_config``), ``config.load()`` short-circuits without
    hitting SSM."""
    from app.main import create_app

    api = create_app(load_config=True)
    assert isinstance(api, FastAPI)


def test_build_module_app_without_skip_env_calls_load(
    seed_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branch where ``CONTRICOOL_SKIP_COLD_START_CONFIG`` is not set
    must still build successfully when the config cache is pre-warmed."""
    monkeypatch.delenv("CONTRICOOL_SKIP_COLD_START_CONFIG", raising=False)
    from app.main import _build_module_app

    api = _build_module_app()
    assert isinstance(api, FastAPI)
