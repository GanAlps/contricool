"""``Contricool-{env}-Api`` stack.

Creates the FastAPI Lambda + API Gateway HTTP API for an environment.

- Lambda runs an arm64 container image built from ``apps/api/Dockerfile``,
  with the AWS Lambda Web Adapter forwarding API Gateway events to a
  ``uvicorn`` process listening on port 8080 inside the container.
- Lambda has reserved concurrency 100 (red-line 2 cost guardrail).
- ``snapstart`` constructor parameter is wired but is **off** at MVP:
  AWS Lambda does not support SnapStart on container-image functions
  (only zip-packaged Java/Python/.NET). The stack still publishes a
  ``Version`` and ``live`` ``Alias`` for blue/green-style alias-shift
  rollback, since those are independent of SnapStart.
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
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ecr_assets as ecr_assets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from constructs import Construct

# Auth-bootstrap routes (Design 4 / Phase 2c) that are reachable
# without a JWT — explicit ``add_routes`` with no authorizer wins
# over the catch-all ``/{proxy+}`` (HTTP API: more specific wins).
_PUBLIC_AUTH_PATHS: list[str] = [
    "/v1/auth/signup",
    "/v1/auth/verify-email",
    "/v1/auth/resend-email-code",
    "/v1/auth/login",
    "/v1/auth/refresh",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
]

# Per-route throttling — CLAUDE.md red-line 2 cost guardrails.
_ROUTE_THROTTLES: dict[str, dict[str, int]] = {
    "POST /v1/auth/login": {"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10},
    "POST /v1/auth/resend-email-code": {
        "ThrottlingRateLimit": 1,
        "ThrottlingBurstLimit": 5,
    },
    "POST /v1/auth/forgot-password": {
        "ThrottlingRateLimit": 1,
        "ThrottlingBurstLimit": 5,
    },
}

# Cognito IAM actions the Lambda needs — enumerated, never ``*``.
_COGNITO_ACTIONS: list[str] = [
    "cognito-idp:SignUp",
    "cognito-idp:ConfirmSignUp",
    "cognito-idp:ResendConfirmationCode",
    "cognito-idp:InitiateAuth",
    "cognito-idp:GlobalSignOut",
    "cognito-idp:ForgotPassword",
    "cognito-idp:ConfirmForgotPassword",
    "cognito-idp:AdminGetUser",
]

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
        user_pool: cognito.IUserPool,
        web_client: cognito.IUserPoolClient,
        ios_client: cognito.IUserPoolClient,
        android_client: cognito.IUserPoolClient,
        users_table: dynamodb.ITable,
        reserved_concurrent_executions: int = 100,
        prod_cmk: kms.IKey | None = None,
        app_version: str = "0.0.1-dev",
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._env_name = env_name
        is_prod = env_name == "prod"
        self._app_version = app_version

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
            reserved_concurrent_executions=reserved_concurrent_executions,
            environment={
                "POWERTOOLS_SERVICE_NAME": "contricool-api",
                "POWERTOOLS_LOG_LEVEL": "INFO",
                "ENV_NAME": env_name,
                "APP_VERSION": app_version,
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/extensions/lambda-adapter",
            },
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
        )

        # IAM grants for Phase 2b cold-start config loading. The Lambda
        # reads /contricool/<env>/{cognito,ddb}/* and the
        # /contricool/<env>/pii-salt SecureString from SSM at init via a
        # single ``ssm:GetParameters`` (plural batch) call. KMS Decrypt is
        # needed in prod where the salt is encrypted with the project CMK
        # (dev uses the AWS-managed alias/aws/ssm so no CMK grant
        # required).
        self.lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/contricool/{env_name}/*",
                ],
            )
        )
        if is_prod:
            if prod_cmk is None:
                raise ValueError(
                    "prod ApiStack requires the project CMK to decrypt "
                    "the PII salt SecureString. Pass prod_cmk via app.py."
                )
            prod_cmk.grant_decrypt(self.lambda_function)

        # Phase 2c — Cognito + DDB grants for the auth feature.
        # Enumerated cognito-idp actions only — no ``*``. Resource is
        # the per-env pool ARN; cross-env access is impossible.
        self.lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=list(_COGNITO_ACTIONS),
                resources=[user_pool.user_pool_arn],
            )
        )
        # DDB: GetItem/PutItem/UpdateItem only — no Scan, no
        # BatchWriteItem, no DeleteItem. ``grant`` (singular) keeps the
        # action set tight; ``grant_read_write_data`` would add Scan +
        # BatchWriteItem which we explicitly reject.
        users_table.grant(
            self.lambda_function,
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
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

        # SnapStart — kept gated behind ``snapstart`` so this code stays
        # ready for the day AWS adds container-image support (or we switch
        # to a zip-packaged Lambda). Today setting this to True yields a
        # CFN ``CREATE_FAILED`` with
        # "ContainerImage is not supported for SnapStart enabled functions".
        # ``app.py`` forces ``snapstart=False`` for both envs at MVP.
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

        # JWT authorizer for ``/v1/*`` — Phase 2c. We use the L1
        # ``CfnAuthorizer`` because the ``aws_apigatewayv2_authorizers_alpha``
        # module is unstable and pinning brings constant CDK upgrade
        # churn. Direct CFN keeps the construct surface narrow.
        cfn_authorizer = apigwv2.CfnAuthorizer(
            self,
            "JwtAuthorizer",
            api_id=self.api_gateway.api_id,
            authorizer_type="JWT",
            identity_source=["$request.header.Authorization"],
            jwt_configuration=apigwv2.CfnAuthorizer.JWTConfigurationProperty(
                audience=[
                    web_client.user_pool_client_id,
                    ios_client.user_pool_client_id,
                    android_client.user_pool_client_id,
                ],
                issuer=(
                    f"https://cognito-idp.{self.region}.amazonaws.com/"
                    f"{user_pool.user_pool_id}"
                ),
            ),
            name=f"contricool-{env_name}-jwt-authorizer",
        )

        # Public auth-bootstrap routes — explicit, no authorizer. HTTP
        # API picks the more-specific match before the catch-all.
        for path in _PUBLIC_AUTH_PATHS:
            self.api_gateway.add_routes(
                path=path,
                methods=[apigwv2.HttpMethod.POST],
                integration=integration,
            )

        # ``/v1/health`` is also public; it's already implicit under the
        # catch-all pattern below, so we declare an explicit route to
        # bypass the JWT authorizer that the catch-all attaches.
        self.api_gateway.add_routes(
            path="/v1/health",
            methods=[apigwv2.HttpMethod.GET],
            integration=integration,
        )

        # Catch-all route — JWT authorizer attached via L1 override.
        # The L2 ``add_routes`` returns the created routes; we patch
        # each one to point at the authorizer.
        catchall_routes = self.api_gateway.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
        )
        for route in catchall_routes:
            cfn_route = route.node.default_child
            assert isinstance(cfn_route, cdk.CfnResource)
            cfn_route.add_property_override("AuthorizerId", cfn_authorizer.ref)
            cfn_route.add_property_override("AuthorizationType", "JWT")

        # Authenticated explicit routes — POST /v1/auth/logout requires JWT.
        logout_routes = self.api_gateway.add_routes(
            path="/v1/auth/logout",
            methods=[apigwv2.HttpMethod.POST],
            integration=integration,
        )
        for route in logout_routes:
            cfn_route = route.node.default_child
            assert isinstance(cfn_route, cdk.CfnResource)
            cfn_route.add_property_override("AuthorizerId", cfn_authorizer.ref)
            cfn_route.add_property_override("AuthorizationType", "JWT")

        # Stage-level throttling — defense in depth at API Gateway.
        # Values match CLAUDE.md red-line 2: 5,000 RPS / 10,000 burst,
        # plus per-route tighter throttling on hot auth routes.
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
            cfn_default_stage.add_property_override(
                "RouteSettings",
                _ROUTE_THROTTLES,
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

