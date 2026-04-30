"""Structured logging + metrics + tracing with PII redaction.

The redaction layer is the safety-critical surface: every PR that touches
this module needs negative-test coverage that would catch a regression.
``DENY_KEYS`` lists the fragments (after splitting a key on
``_``/``-``/CamelCase) that mark a value as PII or secret;
``DENY_COMPOUND_KEYS`` covers multi-word keys whose individual fragments
are too generic to deny on their own (e.g., ``credit_card`` —
``credit`` and ``card`` are both fine in isolation, but the combination
is a credit-card number).

``redact()`` walks any nested dict/list and replaces matching values
with ``[REDACTED]``. The Powertools Logger is wired through a custom
``RedactingFormatter`` so **every** ``logger.info / .error / .warning``
call routed through the project Logger goes through ``redact()`` before
serialisation, regardless of whether the caller remembered to wrap their
``extra`` dict.

The deny set is deliberately superset-y — `customer_email` redacts
because ``email`` is in the deny list. Substring-matching the whole key
would over-match (`secrets_count` would falsely redact); whole-fragment
matching on `_`/`-`/CamelCase-split parts is the right default.
"""
from __future__ import annotations

import json
import re
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.logging.formatter import LambdaPowertoolsFormatter

# Key fragments that mark a value as PII or a secret. Match is
# whole-fragment, case-insensitive (see ``_is_sensitive_key``).
DENY_KEYS: frozenset[str] = frozenset(
    {
        "email",
        "phone",
        "password",
        "otp",
        "authorization",
        "cookie",
        "secret",
        "token",
        "ssn",
        "salt",
    }
)

# Compound keys whose joined form is sensitive. ``credit`` and ``card``
# are too generic to deny independently (``discount_card``, ``credit_score``);
# the combination is a credit-card number and must redact.
DENY_COMPOUND_KEYS: frozenset[str] = frozenset(
    {
        "credit_card",
        "credit_card_number",
        "card_number",
        "cc_number",
        "ccn",
    }
)

# ``code`` is intentionally NOT in DENY_KEYS — it would over-redact useful
# operational keys like ``status_code``. Cognito verification codes appear
# in keys named ``otp`` or ``confirmation_code`` (latter splits to
# ``confirmation``+``code``, neither matched). The real defence against
# logging raw codes is "never log request bodies"; the middleware enforces
# that. If a future code path needs to log a code, name the field ``otp``.

# Fragment separators used when splitting a key for whole-fragment matching.
# Covers ``snake_case``, ``kebab-case``, and CamelCase boundaries (the regex
# below). ``set-cookie`` and ``access_token`` reduce to the same fragments.
_SPLIT_RE = re.compile(r"[_\-\s]|(?<=[a-z])(?=[A-Z])")
# Normalise compound-key matching: lowercase + collapse separators to ``_``
# so ``creditCard``, ``credit-card``, and ``credit_card`` all hit
# DENY_COMPOUND_KEYS uniformly.
_NORMALISE_RE = re.compile(r"[\-\s]+")

_REDACTED = "[REDACTED]"


def _normalise_compound(key: str) -> str:
    # Insert ``_`` at CamelCase boundaries first, then collapse other
    # separators, then lowercase.
    camelled = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", key)
    return _NORMALISE_RE.sub("_", camelled).lower()


def _is_sensitive_key(key: object) -> bool:
    """Return True if ``key`` matches DENY_KEYS or DENY_COMPOUND_KEYS."""
    if not isinstance(key, str):
        return False
    if _normalise_compound(key) in DENY_COMPOUND_KEYS:
        return True
    fragments = {frag.lower() for frag in _SPLIT_RE.split(key) if frag}
    return bool(fragments & DENY_KEYS)


def redact(obj: Any) -> Any:
    """Return a copy of ``obj`` with sensitive values replaced.

    - dict: each (key, value) pair is inspected; matching keys map to
      ``[REDACTED]`` regardless of value type. Non-matching values are
      recursed into.
    - list / tuple: each element is recursed into; tuples become lists in
      the output (we only need this for log-record shape).
    - everything else: returned unchanged.
    """
    if isinstance(obj, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple):
        return [redact(item) for item in obj]
    return obj


def redact_json(blob: str) -> str:
    """Best-effort redaction over a JSON-encoded string.

    Used by middleware to redact request bodies that arrive as raw bytes.
    Falls back to ``[REDACTED]`` if it doesn't parse — never leak raw
    input.
    """
    try:
        decoded = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return _REDACTED
    return json.dumps(redact(decoded), separators=(",", ":"))


# ---- value-level PII scrubbers --------------------------------------
#
# The key-name redactor (above) catches dicts whose keys are sensitive
# (e.g. ``email``, ``token``). It does NOT scrub free-text values like
# user-posted error ``message`` strings, where the key is something
# benign (``message``) but the value happens to contain an email or a
# JWT. The frontend telemetry endpoint accepts arbitrary text and
# logs it via ``logger.warning("frontend_telemetry", extra={...})`` —
# so we need a value-level pass on the strings before they hit the
# logger.

# RFC-5322-shaped email address. Permissive but contains the common
# shape; false positives (e.g. "version 1.0@2026") are rare and the
# cost of an over-redact is one less debug clue, vs. the cost of a
# leak which is irreversible.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,24}\b"
)
# E.164-ish phone numbers — the ``+`` is required so we don't strip
# every number from a user's stack trace.
_PHONE_RE = re.compile(r"\+\d{7,15}")
# JWTs — three base64url segments separated by dots. Conservative
# minimum length so we don't strip every dotted identifier.
_JWT_RE = re.compile(r"\b[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")
# AWS access keys (red-line 1 — never log).
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def scrub_pii_text(text: str) -> str:
    """Strip likely-PII substrings from a free-text value.

    Used by the frontend telemetry route on user-posted ``message``,
    ``stack``, ``url``, and ``user_agent`` fields. Each match is
    replaced with ``[REDACTED]`` regardless of length or kind.

    The order matters: JWT before AWS-key + email so a token that
    happens to contain an email-shape inside a base64-decoded blob
    is fully scrubbed.
    """
    if not isinstance(text, str) or not text:
        return text
    out = _JWT_RE.sub(_REDACTED, text)
    out = _AWS_KEY_RE.sub(_REDACTED, out)
    out = _EMAIL_RE.sub(_REDACTED, out)
    out = _PHONE_RE.sub(_REDACTED, out)
    return out


def _redacting_serializer(record: Any) -> str:
    """JSON-serialise a log record with redaction applied first."""
    return json.dumps(redact(record), default=str, separators=(",", ":"))


class RedactingFormatter(LambdaPowertoolsFormatter):
    """Powertools formatter that pipes the log record dict through
    ``redact`` before JSON serialisation.

    Every ``logger.info / .warning / .error`` call routed through the
    project ``Logger`` goes through this formatter, so a feature handler
    that accidentally calls ``logger.info("X", extra={"email": val})``
    still emits ``"email": "[REDACTED]"`` — defence in depth on top of
    the per-call discipline asked of feature code.
    """

    def __init__(self) -> None:
        super().__init__(json_serializer=_redacting_serializer)


# Project-wide instances. Imported by feature modules; configured once.
logger: Logger = Logger(
    service="contricool-api",
    logger_formatter=RedactingFormatter(),
)
metrics: Metrics = Metrics(namespace="ContriCool/API", service="contricool-api")
tracer: Tracer = Tracer(service="contricool-api")
