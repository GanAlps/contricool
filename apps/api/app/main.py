"""FastAPI entry point.

The Lambda Web Adapter forwards HTTP-shaped events from API Gateway to a
``uvicorn`` process running this module; the ASGI ``app`` symbol below is
what LWA expects.

We split the build into ``create_app()`` so tests can construct a fresh
application per fixture without re-importing — Lambda imports this
module once per cold start, calls ``config.load()`` to populate the
SSM-backed config cache, and wires up the core middleware before mounting
feature routers.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.core import config
from app.core.middleware import install_core_middleware
from app.features.auth import routes as auth_routes
from app.features.auth.errors import install_error_handlers
from app.features.friends import routes as friends_routes
from app.routes import health


def create_app(*, load_config: bool = True) -> FastAPI:
    """Build a FastAPI app with core middleware + feature routers.

    ``load_config`` defaults to True for production; tests pass False
    after seeding the config cache via ``config._set_for_tests`` so
    they don't hit SSM.
    """
    if load_config:
        config.load()

    api = FastAPI(
        title="ContriCool API",
        version="0.0.1",
        docs_url=None,        # OpenAPI spec is a built artifact, not Swagger UI
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    install_core_middleware(api)
    install_error_handlers(api)
    api.include_router(health.router, prefix="/v1", tags=["health"])
    api.include_router(auth_routes.router, prefix="/v1")
    api.include_router(friends_routes.router, prefix="/v1")
    return api


def _build_module_app() -> FastAPI:
    """Build the module-level ``app`` for AWS Lambda Web Adapter.

    In production, ``load_config=True`` triggers the SSM cold-start fetch.
    In tests, ``CONTRICOOL_SKIP_COLD_START_CONFIG=1`` (set by
    ``tests/conftest.py``) keeps import cheap so test collection doesn't
    require AWS credentials. Tests obtain a fresh app via the ``app``
    pytest fixture, which seeds the config cache first.
    """
    import os

    if os.environ.get("CONTRICOOL_SKIP_COLD_START_CONFIG"):
        return create_app(load_config=False)
    return create_app()


# Module-level app instance for AWS Lambda Web Adapter to discover.
app: FastAPI = _build_module_app()
