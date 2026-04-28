"""``Contricool-{env}-Api`` stack.

Creates the FastAPI Lambda + API Gateway HTTP API for an environment.

- Lambda runs an arm64 container image built from ``apps/api/Dockerfile``,
  with the AWS Lambda Web Adapter forwarding API Gateway events to a
  ``uvicorn`` process listening on port 8080 inside the container.
- Lambda has reserved concurrency 100 (red-line 2 cost guardrail).
- SnapStart is enabled on published versions; a ``live`` alias points to the
  latest published version.
- API Gateway HTTP API has a single catch-all route forwarding to the alias.
- Permissive CORS at API Gateway is fine because the public surface is
  same-origin via CloudFront (Design 9); strict CORS is enforced at the
  CloudFront response-headers policy in ``edge_stack.py``.
"""
from __future__ import annotations

from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as apigwv2_integrations,
)
from aws_cdk import (
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from constructs import Construct

_LOG_RETENTION_DAYS_TO_ENUM: dict[int, logs.RetentionDays] = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
}


def _log_retention(days: int) -> logs.RetentionDays:
    if days not in _LOG_RETENTION_DAYS_TO_ENUM:
        raise ValueError(f"Unsupported log retention: {days}")
    return _LOG_RETENTION_DAYS_TO_ENUM[days]


class ApiStack(Stack):
    """API Gateway HTTP API + Lambda function for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        snapstart: bool,
        log_retention_days: int,
        xray_sampling_rate: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._env_name = env_name

        # Explicit LogGroup so we can set retention without using the
        # deprecated `log_retention` Function param.
        log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name=f"/aws/lambda/contricool-api-{env_name}",
            retention=_log_retention(log_retention_days),
            removal_policy=RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN,
        )

        # Lambda function — container image built from ../api.
        # Path is relative to the cdk.json directory, which is apps/infra/.
        self.lambda_function = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            function_name=f"contricool-api-{env_name}",
            code=lambda_.DockerImageCode.from_image_asset(
                directory="../api",
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.seconds(10),
            reserved_concurrent_executions=100,
            environment={
                "POWERTOOLS_SERVICE_NAME": "contricool-api",
                "POWERTOOLS_LOG_LEVEL": "INFO",
                "ENV_NAME": env_name,
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/extensions/lambda-adapter",
            },
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
        )

        # X-Ray sampling rate is documented; concrete sampling rule lives in
        # the X-Ray service config and is set as part of the monitoring stack.
        # (Tracing.ACTIVE here means the function emits segments; the rate is
        # controlled at the API Gateway / X-Ray rule level.)
        cdk.CfnOutput(
            self,
            "XRaySamplingRate",
            value=str(xray_sampling_rate),
            description=f"X-Ray sampling rate for {env_name} (informational)",
        )

        # SnapStart — applied via CFN property override (CDK L2 doesn't yet
        # expose snap_start uniformly across all docker-image runtimes).
        if snapstart:
            cfn_function = self.lambda_function.node.default_child
            assert isinstance(cfn_function, cdk.CfnResource)
            cfn_function.add_property_override(
                "SnapStart", {"ApplyOn": "PublishedVersions"}
            )

        # Published version + ``live`` alias. Required for SnapStart and for
        # the deploy workflow's blue/green-style alias-shift rollback story.
        version = lambda_.Version(
            self,
            "ApiFunctionVersion",
            lambda_=self.lambda_function,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.lambda_alias = lambda_.Alias(
            self,
            "ApiFunctionLiveAlias",
            alias_name="live",
            version=version,
        )

        # API Gateway HTTP API.
        self.api_gateway = apigwv2.HttpApi(
            self,
            "ApiGateway",
            api_name=f"contricool-api-{env_name}",
            description=f"ContriCool API ({env_name})",
            cors_preflight=apigwv2.CorsPreflightOptions(
                # MVP web client is same-origin via CloudFront, so CORS at
                # this layer is mostly defensive. Strict origin allowlist
                # lives at the CloudFront response-headers policy.
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_origins=["*"],
                allow_headers=[
                    "authorization",
                    "content-type",
                    "idempotency-key",
                    "if-match",
                    "x-api-version",
                ],
                max_age=Duration.minutes(10),
            ),
            disable_execute_api_endpoint=False,
        )

        integration = apigwv2_integrations.HttpLambdaIntegration(
            "ApiLambdaIntegration",
            handler=self.lambda_alias,
        )
        self.api_gateway.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
        )

        # Stage-level throttling — defense in depth at API Gateway.
        # Values match CLAUDE.md red-line 2: 5,000 RPS / 10,000 burst.
        # Per-route tighter throttling for hot routes (auth, friends/add)
        # lands in Phase 2 once those routes exist.
        default_stage = self.api_gateway.default_stage
        assert default_stage is not None, "HttpApi default_stage should always exist"
        cfn_default_stage = default_stage.node.default_child
        if isinstance(cfn_default_stage, cdk.CfnResource):
            cfn_default_stage.add_property_override(
                "DefaultRouteSettings",
                {
                    "ThrottlingBurstLimit": 10000,
                    "ThrottlingRateLimit": 5000,
                },
            )

        cdk.CfnOutput(
            self,
            "ApiGatewayEndpoint",
            value=self.api_gateway.api_endpoint,
            description=(
                "Internal API Gateway endpoint — used by CloudFront origin only; "
                "do NOT expose this URL in client code (CLAUDE.md red-line 1)."
            ),
        )

