"""``POST /v1/telemetry/error`` — frontend error + web-vitals sink.

Public route (no JWT required). Per-route throttling lives at API
Gateway (10 RPS / 20 burst, set in ``api_stack.py``). The Lambda
just logs the event into CloudWatch — no DDB write, no Cognito
call — so the telemetry path is cheap even under bursts.

PII handling — CLAUDE.md red-line 1:

The project's structured-log redactor in
``app/core/observability.py`` is **key-name-based** — it scrubs
values whose keys contain ``email`` / ``phone`` / ``token`` /
etc. That doesn't help here because user-posted text lands under
benign key names like ``telemetry_message``. We therefore run a
value-level scrub (:func:`observability.scrub_pii_text`) over
every free-text field before it hits the logger, plus a
key-name redactor pass on the structured ``extra`` dict (which
also catches a frontend that posts ``extra={"email": "..."}``).

The Pydantic model's ``extra="forbid"`` is the third defence: a
malicious frontend can't post arbitrary top-level keys.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, status

from app.core.observability import logger, redact, scrub_pii_text
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


def _scrub_and_truncate(text: str, limit: int) -> str:
    """Run value-level PII scrub first, then truncate.

    Order matters — truncating first could split an email/JWT in
    the middle and leave a substring that the regex misses.
    """
    return _truncate(scrub_pii_text(text), limit)


@router.post(
    "/error",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TelemetryAck,
)
def record_telemetry_event(event: TelemetryEvent) -> TelemetryAck:
    """Log a structured frontend telemetry event.

    ``level=error`` lands at WARNING (an alert-worthy frontend
    crash), ``level=metric`` at INFO (one-shot performance sample).

    Every free-text field is scrubbed of email / phone / JWT / AWS
    access-key shapes before logging. The ``extra`` dict is
    additionally key-name-redacted so a frontend that posts
    ``extra={"email": "x@y.com"}`` still emits ``"email":
    "[REDACTED]"`` in the log line.
    """
    # Key-name redact the dict, THEN serialise. The serialised JSON
    # is also value-scrubbed in case a non-deny key (e.g. ``user_email``
    # — actually caught by the redactor — but more importantly a
    # totally benign key like ``url_param``) carries a PII string.
    extra_redacted = redact(event.extra)
    extra_json = scrub_pii_text(json.dumps(extra_redacted, default=str))

    payload = {
        "telemetry_event": event.name,
        "telemetry_level": event.level,
        "telemetry_message": _scrub_and_truncate(event.message, 1_000),
        "telemetry_url": _scrub_and_truncate(event.url, 1_000),
        "telemetry_user_agent": _scrub_and_truncate(event.user_agent, 256),
        "telemetry_value": event.value,
        "telemetry_extra": _truncate(extra_json, 1_000),
        "telemetry_stack": _scrub_and_truncate(event.stack, _MAX_LOG_BYTES),
    }
    if event.level == "error":
        logger.warning("frontend_telemetry", extra=payload)
    else:
        logger.info("frontend_telemetry", extra=payload)
    return TelemetryAck()
