"""Cold-start configuration loader.

Reads the per-environment runtime config from AWS SSM Parameter Store at
container init and caches the result in module scope. A single
``ssm:GetParameters`` batch covers every name we need; subsequent calls
within the same warm container short-circuit to the cache.

Failure modes are loud:

- Any missing parameter raises ``RuntimeError`` with the parameter name
  in the message — that's a deploy-time misconfiguration (Phase 2a's
  ``deploy.yml`` step writes these; if a name is missing, the deploy
  pipeline did not run a previous deploy successfully).
- An empty parameter value also raises — silently degrading to a default
  is exactly the kind of surprise we want to avoid in prod.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import boto3

_PARAMETER_KEYS: dict[str, str] = {
    # field on AppConfig                                  → SSM Parameter Name
    "cognito_user_pool_id":     "/contricool/{env}/cognito/user-pool-id",
    "cognito_web_client_id":    "/contricool/{env}/cognito/client-id-web",
    "cognito_ios_client_id":    "/contricool/{env}/cognito/client-id-ios",
    "cognito_android_client_id":"/contricool/{env}/cognito/client-id-android",
    "users_table_name":         "/contricool/{env}/ddb/users-table-name",
    "transactions_table_name":  "/contricool/{env}/ddb/transactions-table-name",
    "pii_salt":                 "/contricool/{env}/pii-salt",
}


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Frozen runtime configuration, populated once per cold start."""

    env_name: str
    aws_region: str
    app_version: str
    cognito_user_pool_id: str
    cognito_web_client_id: str
    cognito_ios_client_id: str
    cognito_android_client_id: str
    users_table_name: str
    transactions_table_name: str
    pii_salt: str


_cache: AppConfig | None = None
_lock = threading.Lock()


def load() -> AppConfig:
    """Return the cached ``AppConfig``, fetching from SSM on first call."""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:  # pragma: no cover - rare thread race
            # Defensive double-checked locking: a concurrent invocation
            # may have populated the cache while this caller waited on
            # the lock. Practically never hit in Lambda's
            # single-threaded-per-container model, but the lock + the
            # second check are still cheaper than a redundant SSM round
            # trip if it ever does.
            return _cache
        _cache = _build_from_ssm()
        return _cache


def _set_for_tests(config: AppConfig | None) -> None:
    """Test hook: directly assign or clear the cache. Never call in prod."""
    global _cache
    _cache = config


def _build_from_ssm() -> AppConfig:
    env_name = _require_env("ENV_NAME")
    aws_region = _require_env("AWS_REGION")
    app_version = os.environ.get("APP_VERSION", "0.0.1")

    names_by_field: dict[str, str] = {
        field: tmpl.format(env=env_name) for field, tmpl in _PARAMETER_KEYS.items()
    }
    name_to_field: dict[str, str] = {v: k for k, v in names_by_field.items()}

    ssm = boto3.client("ssm", region_name=aws_region)
    response = ssm.get_parameters(
        Names=list(names_by_field.values()),
        WithDecryption=True,
    )

    invalid = list(response.get("InvalidParameters") or [])
    if invalid:
        raise RuntimeError(
            f"Required SSM parameters missing: {sorted(invalid)}. "
            "This is a deploy-time misconfiguration; check that "
            "deploy.yml ran the 'Write … to SSM' step (Phase 2a)."
        )

    values: dict[str, str] = {}
    for param in response.get("Parameters") or []:
        name = param["Name"]
        value = param.get("Value", "")
        if not value:
            raise RuntimeError(
                f"SSM parameter {name!r} is empty. Re-run the deploy "
                "pipeline; an empty value indicates a partial deploy."
            )
        values[name_to_field[name]] = value

    missing_fields = set(names_by_field) - values.keys()
    if missing_fields:
        raise RuntimeError(
            f"SSM returned no value for fields: {sorted(missing_fields)}. "
            "This usually means the parameter exists but lacks read perms; "
            "check the Lambda execution role's ssm:GetParameters policy."
        )

    return AppConfig(
        env_name=env_name,
        aws_region=aws_region,
        app_version=app_version,
        **values,
    )


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Required Lambda environment variable {key!r} is unset; "
            "set it in apps/infra/stacks/api_stack.py."
        )
    return value
