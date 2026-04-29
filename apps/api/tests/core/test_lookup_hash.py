"""Tests for ``app.core.lookup_hash.email_hash``."""
from __future__ import annotations

import dataclasses
import re

import pytest

from app.core import config
from app.core.config import AppConfig
from app.core.lookup_hash import email_hash


def _swap_salt(salt: str) -> AppConfig:
    new = dataclasses.replace(config.load(), pii_salt=salt)
    config._set_for_tests(new)
    return new


def test_hash_is_deterministic(seed_config: AppConfig) -> None:
    assert email_hash("alice@example.com") == email_hash("alice@example.com")


def test_hash_normalises_case_and_whitespace(seed_config: AppConfig) -> None:
    canonical = email_hash("alice@example.com")
    assert email_hash("  alice@example.com  ") == canonical
    assert email_hash("Alice@Example.com") == canonical
    assert email_hash("ALICE@EXAMPLE.COM") == canonical


def test_hash_empty_input_raises(seed_config: AppConfig) -> None:
    with pytest.raises(ValueError):
        email_hash("")


def test_hash_whitespace_only_input_raises(seed_config: AppConfig) -> None:
    with pytest.raises(ValueError):
        email_hash("   ")


@pytest.mark.parametrize("bad_input", [None, 42, ["a@b.com"], {"email": "a@b.com"}])
def test_hash_non_string_input_raises(
    seed_config: AppConfig,
    bad_input: object,
) -> None:
    with pytest.raises(ValueError):
        email_hash(bad_input)  # type: ignore[arg-type]


def test_hash_output_is_64_char_lowercase_hex(seed_config: AppConfig) -> None:
    out = email_hash("alice@example.com")
    assert len(out) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", out)


def test_hash_changes_with_salt(seed_config: AppConfig) -> None:
    """Different salt → different hash. Locks the property that the salt
    is actually feeding the HMAC (not silently ignored)."""
    h1 = email_hash("alice@example.com")
    _swap_salt("alternate-salt-value")
    h2 = email_hash("alice@example.com")
    assert h1 != h2
    # Restore the seed for any later tests on the same module.
    _swap_salt(seed_config.pii_salt)


def test_hash_distinguishes_distinct_emails(seed_config: AppConfig) -> None:
    assert email_hash("alice@example.com") != email_hash("bob@example.com")
