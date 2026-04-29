"""JWT verification against a Cognito User Pool.

Phase 2c adds Lambda-side defense-in-depth on top of API Gateway HTTP
API's JWT authorizer: every authenticated route depends on
``current_principal()`` (in ``dependencies.py``) which calls
:class:`JwtVerifier` to re-validate the token before the handler runs.

The verifier:

- Fetches the pool's JWKs once per cold start (``PyJWKClient`` caches in
  process memory).
- On a ``kid`` miss — Cognito has rotated keys — refetches once. A
  persistent miss raises :class:`InvalidTokenError`.
- Validates ``iss`` exactly equal to the per-env Cognito issuer URL;
  ``token_use`` must be ``"id"`` or ``"access"``; ``exp`` is checked by
  ``pyjwt``.
- Validates audience: ID tokens carry ``aud`` (must be one of our three
  app-client IDs); access tokens carry ``client_id`` (same allow-list).
- Returns the validated claims dict — callers (``Principal.from_claims``)
  pull out ``custom:user_id``, ``email``, ``name``.

We deliberately **do not** log the token, the email, or any claim value
on a verification failure: an attacker doesn't get a free oracle telling
them which check failed. ``current_principal`` translates to a generic
401 ``UNAUTHENTICATED`` envelope.
"""
from __future__ import annotations

from typing import Final

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

_ALLOWED_TOKEN_USE: Final[frozenset[str]] = frozenset({"id", "access"})


class InvalidTokenError(Exception):
    """Raised whenever a token fails any verification step."""


class JwtVerifier:
    """Verify Cognito-signed JWTs against a fixed issuer + audience set."""

    def __init__(
        self,
        *,
        issuer: str,
        audience_ids: list[str],
        jwks_url: str | None = None,
    ) -> None:
        if not issuer:
            raise ValueError("issuer is required")
        if not audience_ids:
            raise ValueError("audience_ids must contain at least one app client ID")
        self._issuer = issuer
        self._audience_ids = frozenset(audience_ids)
        self._jwks_url = jwks_url or f"{issuer}/.well-known/jwks.json"
        # cache_keys=True so the same kid round-trips through process
        # memory; lifetime_in_seconds keeps a refresh window so a rotated
        # key is picked up within a cold-start lifecycle.
        self._jwk_client = PyJWKClient(self._jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict[str, object]:
        """Validate ``token`` and return the claims dict.

        Raises :class:`InvalidTokenError` on any failure.
        """
        if not token or not isinstance(token, str):
            raise InvalidTokenError("empty token")
        try:
            signing_key = self._signing_key_with_retry(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                # Cognito access tokens use ``client_id`` (not ``aud``),
                # so we disable pyjwt's automatic audience check and run
                # the right one ourselves below.
                options={"verify_aud": False, "require": ["exp", "iss", "token_use"]},
            )
        except PyJWTError as exc:
            raise InvalidTokenError(f"jwt decode failed: {type(exc).__name__}") from exc

        token_use = claims.get("token_use")
        if token_use not in _ALLOWED_TOKEN_USE:
            raise InvalidTokenError(f"unsupported token_use: {token_use!r}")

        if token_use == "id":
            aud = claims.get("aud")
            if aud not in self._audience_ids:
                raise InvalidTokenError("id token aud not in audience list")
        else:  # access token
            client_id = claims.get("client_id")
            if client_id not in self._audience_ids:
                raise InvalidTokenError("access token client_id not in audience list")

        return claims

    def _signing_key_with_retry(self, token: str) -> jwt.PyJWK:
        """Fetch the signing key for ``token`` with one refetch on miss.

        ``PyJWKClient`` caches the JWKs response. If the kid is absent
        from the cache it refetches automatically. We add a single
        explicit refetch on the rare case where the in-process cache is
        warm with a stale set — pyjwt raises ``PyJWKClientError`` in
        that case, and a fresh fetch usually resolves it.
        """
        try:
            return self._jwk_client.get_signing_key_from_jwt(token)
        except PyJWTError as first_err:
            # Bust the cache and try once more.
            self._jwk_client = PyJWKClient(self._jwks_url, cache_keys=True)
            try:
                return self._jwk_client.get_signing_key_from_jwt(token)
            except PyJWTError as second_err:
                raise InvalidTokenError(
                    f"jwks key lookup failed: {type(second_err).__name__}"
                ) from first_err
