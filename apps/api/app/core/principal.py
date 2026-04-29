"""Authenticated-request principal model.

A ``Principal`` is the project-internal projection of a Cognito JWT's
claims after validation. Phase 2b only defines the model and the
``from_claims`` factory; Phase 2c adds the FastAPI dependency that runs
JWT signature verification and constructs a Principal from validated
claims.

Feature handlers receive a ``Principal`` via ``current_principal()``
(coming in Phase 2c) and never inspect raw claims themselves.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, ValidationError


class Principal(BaseModel):
    """The minimum identity surface every authenticated handler needs."""

    user_id: str = Field(min_length=26, max_length=26)
    email: EmailStr
    display_name: str = Field(min_length=1)
    groups: list[str] = Field(default_factory=list)
    token_use: Literal["id", "access"]

    model_config = {"frozen": True}

    @classmethod
    def from_claims(cls, claims: dict[str, object]) -> Principal:
        """Build a Principal from a Cognito-shaped claims dict.

        Raises ``ValueError`` (the parent class of pydantic
        ``ValidationError``) on any missing or malformed required claim;
        callers translate to HTTP 401.
        """
        try:
            return cls(
                user_id=str(claims["custom:user_id"]).strip(),
                email=str(claims["email"]).strip(),
                display_name=str(claims["name"]).strip(),
                groups=_coerce_groups(claims.get("cognito:groups")),
                token_use=str(claims["token_use"]),  # type: ignore[arg-type]
            )
        except KeyError as e:
            raise ValueError(f"Missing required JWT claim: {e}") from e
        except ValidationError as e:
            raise ValueError(f"Invalid JWT claim shape: {e}") from e


def _coerce_groups(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, str):
        return [g for g in raw.split(",") if g]
    raise ValueError(f"cognito:groups must be list or comma-string; got {type(raw)}")
