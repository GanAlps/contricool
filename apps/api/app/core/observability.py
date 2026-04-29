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
