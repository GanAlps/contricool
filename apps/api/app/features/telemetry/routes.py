"""``POST /v1/telemetry/error`` — frontend error + web-vitals sink.

Public route (no JWT required). Per-IP throttling lives at API
Gateway (10/min/IP, set in ``api_stack.py``). The Lambda just logs
the event into CloudWatch — no DDB write, no Cognito call — so the
telemetry path is cheap even under bursts.

CLAUDE.md red-line 1: never log raw email/phone/password/code/
otp/Authorization/Cookie/secret/token/refresh_token. The
log-redaction filter in ``app/core/observability.py`` already
sanitises log records, so a malicious frontend can't post a
"message": "<email>" and have it land verbatim.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, status

from app.core.observability import logger
from app.features.telemetry.models import TelemetryAck, TelemetryEvent

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# How many bytes of the structured event we keep on a single log
# line. CloudWatch supports up to 256 KiB but a pathological
# ``stack`` could blow the budget — 8 KiB is plenty for human review.
_MAX_LOG_BYTES = 8 * 1024


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


@router.post(
    "/error",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TelemetryAck,
)
def record_telemetry_event(event: TelemetryEvent) -> TelemetryAck:
    """Log a structured frontend telemetry event.

    ``level=error`` lands at WARNING (an alert-worthy frontend
    crash), ``level=metric`` at INFO (one-shot performance sample).
    """
    payload = {
        "telemetry_event": event.name,
        "telemetry_level": event.level,
        "telemetry_message": _truncate(event.message, 1_000),
        "telemetry_url": _truncate(event.url, 1_000),
        "telemetry_user_agent": _truncate(event.user_agent, 256),
        "telemetry_value": event.value,
        # ``extra`` rendered as a single JSON blob so the structured
        # logger doesn't choke on dynamic-key fan-out.
        "telemetry_extra": _truncate(json.dumps(event.extra), 1_000),
        "telemetry_stack": _truncate(event.stack, _MAX_LOG_BYTES),
    }
    if event.level == "error":
        logger.warning("frontend_telemetry", extra=payload)
    else:
        logger.info("frontend_telemetry", extra=payload)
    return TelemetryAck()
