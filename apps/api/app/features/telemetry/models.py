"""Pydantic shapes for the frontend telemetry endpoint.

Frontends post uncaught errors + Core Web Vitals here. The shape is
deliberately permissive — any rejected body would just be a missed
data point, and we'd rather observe the noise than reject signal.
The route is rate-limited at API Gateway (10/min/IP) so a bad actor
can't flood the log group.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class TelemetryEvent(BaseModel):
    """One frontend telemetry event.

    ``level=error`` is for uncaught errors / unhandled promise
    rejections.  ``level=metric`` is for Core Web Vitals (LCP, INP,
    CLS, FID, TTFB) plus other custom dimensions.
    """

    model_config = ConfigDict(extra="forbid")

    level: Literal["error", "metric"]
    name: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(max_length=2_000)] = ""
    # Optional fields — frontend may include any subset.
    stack: Annotated[str, Field(max_length=8_000)] = ""
    url: Annotated[str, Field(max_length=2_000)] = ""
    user_agent: Annotated[str, Field(max_length=512)] = ""
    # Numeric value for metric events (LCP ms, CLS score, etc.).
    value: float | None = None
    # Free-form bag — capped to keep one event under the CloudWatch
    # log-line size limit. The route serialises this through json.dumps.
    extra: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )


class TelemetryAck(BaseModel):
    """Trivial 202 acknowledgement so the client knows the event landed."""

    accepted: bool = True
