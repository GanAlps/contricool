"""CFN custom-resource handler that lazily generates the PII lookup salt.

The salt is a 64-character hex string (32 random bytes) used by
``apps/api/app/core/lookup_hash.py`` to HMAC user emails into
``GSI1PK=EMAIL#<hex>`` lookup keys. It is **never rotated** — rotation would
break every existing email lookup row.

This handler runs inside a CDK provider Lambda, not at synth time, so the
generated value never leaks into the synthesized CloudFormation template,
``cdk.out``, or CloudWatch Logs. The handler return payload deliberately
omits the value; the parameter itself is a SecureString encrypted with KMS.

Lifecycle:

- ``Create``: try ``put_parameter(Overwrite=False)``; tolerate
  ``ParameterAlreadyExists`` (re-deploy of an env that already has a salt).
- ``Update``: no-op. Re-emit the same ``PhysicalResourceId`` so CloudFormation
  treats the resource as unchanged.
- ``Delete``: no-op. The salt MUST survive stack destroy/recreate; if an
  operator truly wants a clean slate (and to invalidate every lookup row),
  they must run ``aws ssm delete-parameter`` manually.
"""
from __future__ import annotations

import os
import secrets
from typing import Any

import boto3
from botocore.exceptions import ClientError

_PARAMETER_NAME_ENV = "PII_SALT_PARAMETER_NAME"
_KMS_KEY_ID_ENV = "PII_SALT_KMS_KEY_ID"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_type = event.get("RequestType")
    parameter_name = os.environ[_PARAMETER_NAME_ENV]
    kms_key_id = os.environ.get(_KMS_KEY_ID_ENV) or "alias/aws/ssm"

    physical_id = f"pii-salt::{parameter_name}"

    if request_type == "Create":
        _create_if_missing(parameter_name, kms_key_id)
    # Update / Delete are explicit no-ops. We never rotate or remove the salt.
    return {"PhysicalResourceId": physical_id, "Data": {}}


def _create_if_missing(parameter_name: str, kms_key_id: str) -> None:
    ssm = boto3.client("ssm")
    salt_hex = secrets.token_hex(32)
    try:
        ssm.put_parameter(
            Name=parameter_name,
            Value=salt_hex,
            Type="SecureString",
            KeyId=kms_key_id,
            Overwrite=False,
            Description=(
                "ContriCool PII lookup salt — used to HMAC emails into "
                "GSI1 lookup keys. NEVER rotate (breaks every lookup row)."
            ),
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code", "")
        if code == "ParameterAlreadyExists":
            return
        raise
