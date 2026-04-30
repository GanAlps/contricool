"""Tests for the friends-feature opaque pagination cursor."""
from __future__ import annotations

import pytest

from app.core import config
from app.core.config import AppConfig
from app.features.friends.cursor import InvalidCursorError, decode, encode


@pytest.fixture(autouse=True)
def _seed_config() -> None:
    """Seed a deterministic salt so HMAC is reproducible across tests."""
    config._set_for_tests(
        AppConfig(
            env_name="test",
            aws_region="us-west-2",
            app_version="0.0.1-test",
            cognito_user_pool_id="us-west-2_test",
            cognito_web_client_id="web",
            cognito_ios_client_id="ios",
            cognito_android_client_id="android",
            users_table_name="ContriCool-Users-test",
            transactions_table_name="ContriCool-Transactions-test",
            pii_salt="test-cursor-salt",
        )
    )


def test_encode_decode_round_trip() -> None:
    cursor = encode(requester_id="u-self", last_friend_id="u-friend-99")
    assert decode(cursor=cursor, requester_id="u-self") == "u-friend-99"


def test_decode_with_wrong_requester_rejects() -> None:
    cursor = encode(requester_id="u-self", last_friend_id="u-f")
    with pytest.raises(InvalidCursorError):
        decode(cursor=cursor, requester_id="u-other")


def test_decode_tampered_signature_rejects() -> None:
    cursor = encode(requester_id="u-self", last_friend_id="u-f")
    # Flip a character in the cursor to break the signature.
    bad = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    with pytest.raises(InvalidCursorError):
        decode(cursor=bad, requester_id="u-self")


def test_decode_malformed_base64_rejects() -> None:
    with pytest.raises(InvalidCursorError):
        decode(cursor="!!!not-base64!!!", requester_id="u-self")


def test_decode_missing_separator_rejects() -> None:
    import base64

    raw = "no-dot-here"
    encoded = base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode(cursor=encoded, requester_id="u-self")


def test_decode_empty_payload_rejects() -> None:
    import base64

    raw = ":"
    encoded = base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode(cursor=encoded, requester_id="u-self")


def test_decode_malformed_payload_no_colon_rejects() -> None:
    """A signed but colon-less payload (only last_friend_id, no requester)."""
    from app.features.friends import cursor as c

    payload = "no-colon-here"
    sig = c._sign(payload)
    encoded = c._b64url_encode(f"{payload}{c._SEPARATOR}{sig}")
    with pytest.raises(InvalidCursorError):
        decode(cursor=encoded, requester_id="u-self")


def test_decode_empty_last_friend_id_rejects() -> None:
    """A signed payload with `<requester>:` (empty last_friend_id)."""
    from app.features.friends import cursor as c

    payload = "u-self:"
    sig = c._sign(payload)
    encoded = c._b64url_encode(f"{payload}{c._SEPARATOR}{sig}")
    with pytest.raises(InvalidCursorError):
        decode(cursor=encoded, requester_id="u-self")


def test_decode_empty_cursor_rejects() -> None:
    with pytest.raises(InvalidCursorError):
        decode(cursor="", requester_id="u-self")


def test_decode_non_utf8_bytes_rejects() -> None:
    import base64

    encoded = base64.urlsafe_b64encode(b"\xff\xfe\xfd").rstrip(b"=").decode("ascii")
    with pytest.raises(InvalidCursorError):
        decode(cursor=encoded, requester_id="u-self")


def test_encode_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError):
        encode(requester_id="", last_friend_id="x")
    with pytest.raises(ValueError):
        encode(requester_id="x", last_friend_id="")
