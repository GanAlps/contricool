"""Cross-feature contract test: ``find_user_by_email`` must hit a META
row written by the **real** ``auth.service`` code path.

The seed-helper ``conftest.seed_user`` mirrors the production shape so
the rest of the friends tests pass — but a separate test that drives
``auth.service._put_user_meta`` directly guards against the two
diverging again.  An earlier divergence (GSI1SK="USER" vs the
production "USER#<id>") let the friends-add flow ship to dev silently
404'ing every real lookup.
"""
from __future__ import annotations

from app.features.auth import service as auth_svc
from app.features.friends import repository as friends_repo


def test_friends_lookup_resolves_meta_row_written_by_auth(
    friends_env: dict[str, object],
) -> None:
    user_id = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
    email = "real-auth@example.com"

    # Drive the same private writer that verify_email uses in prod.
    auth_svc._put_user_meta(
        user_id=user_id,
        email=email,
        display_name="Real",
        currency="USD",
    )

    resolved = friends_repo.find_user_by_email(email)
    assert resolved == user_id


def test_friends_lookup_returns_none_for_unknown_email(
    friends_env: dict[str, object],
) -> None:
    assert friends_repo.find_user_by_email("ghost@example.com") is None
