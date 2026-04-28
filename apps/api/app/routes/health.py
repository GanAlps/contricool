"""``GET /v1/health`` — liveness check."""
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    env: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return liveness + build metadata.

    No DDB / Cognito / external calls — this endpoint is invoked by the
    deploy smoke-test step and any external uptime monitor, so it must be
    cheap and side-effect-free.
    """
    return HealthResponse(
        status="ok",
        env=os.environ.get("ENV_NAME", "unknown"),
        version=os.environ.get("APP_VERSION", "0.0.1"),
    )
