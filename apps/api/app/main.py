"""FastAPI entry point.

Phase 1: only ``GET /v1/health`` exists. Subsequent phases mount feature
routers (auth, friends, transactions, …) under ``/v1`` from
``app/features/*``.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.routes import health

app = FastAPI(
    title="ContriCool API",
    version="0.0.1",
    docs_url=None,        # we don't expose Swagger UI; OpenAPI spec is built artifact
    redoc_url=None,
    openapi_url="/openapi.json",
)

app.include_router(health.router, prefix="/v1", tags=["health"])
