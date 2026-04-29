"""``PiiSalt`` construct — a generate-once SSM SecureString.

Wraps a tiny inline-Python provider Lambda (``pii_salt_handler.py``) and a
CFN ``CustomResource``. The provider Lambda creates the parameter on first
deploy and is a deliberate no-op thereafter so the salt is never rotated.

Used by the ``Contricool-{env}-Auth`` stack to seed
``/contricool/<env>/pii-salt`` without leaking the value into the synthesized
CFN template.
"""
from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    CustomResource,
    Duration,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import custom_resources as cr
from constructs import Construct


class PiiSalt(Construct):
    """Idempotent SSM SecureString seed for the project's PII lookup salt."""

    PARAMETER_PATH_TEMPLATE = "/contricool/{env}/pii-salt"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        kms_key_arn: str | None,
    ) -> None:
        super().__init__(scope, construct_id)

        parameter_name = self.PARAMETER_PATH_TEMPLATE.format(env=env_name)
        kms_key_id = kms_key_arn or "alias/aws/ssm"

        # Provider Lambda — runs at CFN custom-resource invocation time only.
        # ``reserved_concurrent_executions=1`` is enough; CFN never invokes
        # this concurrently for the same custom resource.
        handler_dir = Path(__file__).parent
        provider_function = lambda_.Function(
            self,
            "ProviderFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="pii_salt_handler.handler",
            code=lambda_.Code.from_asset(
                str(handler_dir),
                exclude=["__pycache__", "*.pyc", "pii_salt.py", "__init__.py"],
            ),
            timeout=Duration.seconds(10),
            memory_size=256,
            reserved_concurrent_executions=1,
            environment={
                "PII_SALT_PARAMETER_NAME": parameter_name,
                "PII_SALT_KMS_KEY_ID": kms_key_id,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Permissions: PutParameter (Overwrite=False) + GetParameter on the
        # one parameter; KMS Encrypt for SecureString writes when a customer
        # CMK is in play. No DeleteParameter — the salt is permanent.
        ssm_arn = (
            f"arn:aws:ssm:{cdk.Stack.of(self).region}:"
            f"{cdk.Stack.of(self).account}:parameter{parameter_name}"
        )
        provider_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:PutParameter", "ssm:GetParameter"],
                resources=[ssm_arn],
            )
        )
        if kms_key_arn:
            provider_function.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
                    resources=[kms_key_arn],
                )
            )

        provider = cr.Provider(
            self,
            "Provider",
            on_event_handler=provider_function,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        self.parameter_name = parameter_name
        self.custom_resource = CustomResource(
            self,
            "Resource",
            service_token=provider.service_token,
            resource_type="Custom::ContricoolPiiSalt",
            properties={
                # Properties are only used to trigger Update events. We never
                # want Update to do anything, so passing a stable string keeps
                # subsequent deploys idempotent at the CFN diff level.
                "ParameterName": parameter_name,
            },
        )
