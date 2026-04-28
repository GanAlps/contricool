"""Security CDK Aspect — enforces CLAUDE.md red-line guardrails at synth time.

Fails synth (via ``Annotations.add_error``) when a resource violates one of:

- Every S3 bucket must have ``BlockPublicAccess.BLOCK_ALL``
  (red-line 2: no accidental public S3).
- Every Lambda function must have ``ReservedConcurrentExecutions`` set
  (red-line 2: bounded blast radius for runaway loops).

The Aspect inspects the underlying L1 ``CfnBucket`` / ``CfnFunction``
properties directly. We deliberately keep the checks simple — partial /
weakly-set values can be caught by deeper checks added incrementally as
real cases appear; the immediate goal is to prevent the most common
foot-guns (missing config altogether).

CDK creates internal provider Lambdas for several constructs
(``BucketDeployment``, ``auto_delete_objects=True``, custom-resource
providers, log-retention helpers, OIDC provider thumbprint fetcher). We
cannot set ``reserved_concurrent_executions`` on those — they're owned by
the framework. The exemption list below names them by construct-path
substring so the rule still fires on every Lambda we *do* control.
"""
from __future__ import annotations

from typing import Any

import jsii
from aws_cdk import (
    Annotations,
    IAspect,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import IConstruct

# Construct-path tokens that mark CDK-internal provider Lambdas. Matched
# as substrings against ``node.node.path``. Add new entries when CDK
# introduces another framework-managed Lambda we can't configure directly.
_CDK_INTERNAL_LAMBDA_PATH_TOKENS: tuple[str, ...] = (
    "Custom::CDKBucketDeployment",
    "Custom::S3AutoDeleteObjects",
    "AWSCDKOpenIdConnectProvider",
    "LogRetention",
    "Custom::AWS",  # AwsCustomResource
    "framework-onEvent",
    "framework-isComplete",
    "framework-onTimeout",
)


@jsii.implements(IAspect)
class SecurityAspect:
    """Synth-time enforcement of red-line guardrails."""

    def visit(self, node: IConstruct) -> None:
        if isinstance(node, s3.CfnBucket):
            self._check_bucket_block_public(node)
        elif isinstance(node, lambda_.CfnFunction):
            self._check_lambda_reserved_concurrency(node)

    @staticmethod
    def _check_bucket_block_public(node: s3.CfnBucket) -> None:
        # CfnBucket's public_access_block_configuration is the raw L1
        # property. None means the user didn't set BlockPublicAccess at all
        # (the L2 default). We require it to be set.
        config: Any = node.public_access_block_configuration
        if config is None:
            Annotations.of(node).add_error(
                "S3 bucket must have BlockPublicAccess.BLOCK_ALL "
                "(see CLAUDE.md red-line 2)."
            )

    @staticmethod
    def _check_lambda_reserved_concurrency(node: lambda_.CfnFunction) -> None:
        path = node.node.path
        if any(token in path for token in _CDK_INTERNAL_LAMBDA_PATH_TOKENS):
            return
        if node.reserved_concurrent_executions is None:
            Annotations.of(node).add_error(
                f"Lambda function {path} must have "
                "ReservedConcurrentExecutions set "
                "(red-line 2 cost guardrail)."
            )
