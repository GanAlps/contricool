"""Structured logging + metrics + tracing with PII redaction.

The redaction layer is the safety-critical surface: every PR that touches
this module needs negative-test coverage that would catch a regression.
``DENY_KEYS`` lists the substrings (after splitting a key on ``_`` /
``-``) that mark a value as PII or secret. ``redact()`` walks any nested
dict/list and replaces matching values with the literal string
``[REDACTED]`` before the logger serialises the record.

The deny set is deliberately superset-y — `customer_email` redacts because
``email`` is in the deny list. Substring-matching the whole key would
over-match (`secrets_count` would falsely redact); whole-fragment matching
on ``_``/``-``-split parts is the right default.
"""
from __future__ import annotations

import json
import re
from typing import Any

from aws_lambda_powertools import Logger, Metrics, Tracer

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

_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: object) -> bool:
    """Return True if any fragment of ``key`` matches a DENY_KEYS entry."""
    if not isinstance(key, str):
        return False
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
    Falls back to returning the original string if it doesn't parse —
    callers MUST never log a non-JSON request body without explicit
    review (the right behaviour is to log nothing, not a partially-redacted
    blob).
    """
    try:
        decoded = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return _REDACTED  # safe default — never leak raw input
    return json.dumps(redact(decoded), separators=(",", ":"))


# Project-wide instances. Imported by feature modules; configured once.
logger: Logger = Logger(service="contricool-api")
metrics: Metrics = Metrics(namespace="ContriCool/API", service="contricool-api")
tracer: Tracer = Tracer(service="contricool-api")
