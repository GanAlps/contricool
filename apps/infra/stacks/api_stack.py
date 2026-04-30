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
from aws_cdk import (
    aws_ssm as ssm,
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
    # Phase 3a — friend-add carries an app-level rate-limit (30/h per
    # requester); the API Gateway burst cap is the front-line abuse
    # defense.
    "POST /v1/friends/add": {
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
        transactions_table: dynamodb.ITable,
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
                # Phase 4b — exposed for the transactions feature so the
                # repository can pick up the table name without a second
                # SSM read on every cold start (the cold-start config
                # loader still reads the SSM-backed name into AppConfig).
                "TRANSACTIONS_TABLE_NAME": transactions_table.table_name,
            },
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
            # ``current_version`` (used below for the ``live`` alias) inherits
            # these options. ``RETAIN`` keeps prior published versions around
            # so the deploy workflow's alias-shift rollback can re-point
            # ``live`` at the previous version.
            current_version_options=lambda_.VersionOptions(
                removal_policy=RemovalPolicy.RETAIN,
            ),
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
        # DDB: enumerated actions only — no ``*``, no Scan, no
        # BatchWriteItem. ``grant`` (singular) keeps the action set
        # tight; ``grant_read_write_data`` would add Scan +
        # BatchWriteItem which we explicitly reject.
        #
        # Phase 3a additions: ``Query`` (friend list — base + GSI1),
        # ``BatchGetItem`` (hydrate friend names/currencies),
        # ``DeleteItem`` (remove-friend). Canonical-pair friendship
        # insert uses ``PutItem`` with ``attribute_not_exists(PK)``
        # — single-item writes don't need TransactWriteItems.
        #
        # Phase 4b additions: ``ConditionCheckItem`` — required as a
        # ``TransactWriteItems`` operand on the Users table when the
        # transactions feature verifies friendship rows still exist
        # at the moment of the create-transaction transact.
        users_table.grant(
            self.lambda_function,
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:Query",
            "dynamodb:BatchGetItem",
            "dynamodb:DeleteItem",
            "dynamodb:ConditionCheckItem",
        )

        # Phase 4b — Transactions table grants. ``TransactWriteItems``
        # is required for the create-transaction cross-table write
        # spanning Users (friendship ConditionChecks) + Transactions
        # (META + N MEMBERs + AUDIT + IDEMPOTENCY rows). No
        # ``DeleteItem`` on this table — soft-delete is an
        # ``UpdateItem`` (``deleted_at = now``); hard-delete is the
        # Phase 6 cleanup-job's concern.
        transactions_table.grant(
            self.lambda_function,
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:Query",
            "dynamodb:BatchGetItem",
            "dynamodb:ConditionCheckItem",
            "dynamodb:TransactWriteItems",
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
        #
        # ``current_version`` returns a ``Version`` whose CDK logical ID is
        # suffixed with the function's CodeSha256 hash, so a new container
        # image produces a new logical ID, CFN treats it as a new resource,
        # and a fresh immutable version is published — which the alias then
        # tracks. Using a static-ID ``lambda_.Version(...)`` would freeze
        # the alias at whatever code shipped on the very first deploy.
        self.lambda_alias = lambda_.Alias(
            self,
            "ApiFunctionLiveAlias",
            alias_name="live",
            version=self.lambda_function.current_version,
        )

        # Phase 2e: cookie-based refresh requires `allow_credentials=true`
        # which the CORS spec forbids alongside `*` origin.  We list:
        #
        # 1. The deployed CloudFront origin via SSM Dynamic Reference
        #    (`{{resolve:ssm:/contricool/<env>/cloudfront-domain}}`).
        #    CloudFormation resolves this at stack-update time, so the
        #    parameter MUST exist before `cdk deploy` runs.  The deploy
        #    workflow's "Pre-seed cloudfront-domain SSM" step ensures
        #    this on first deploy by writing the placeholder
        #    `placeholder.invalid`; subsequent deploys overwrite it
        #    with the live CloudFront domain (via the "Write CloudFront
        #    domain to SSM" step that runs *after* a successful deploy).
        # 2. Localhost origins for `pnpm --filter @contricool/client dev:web`
        #    so a developer running the SPA locally against the deployed
        #    dev API can sign in / refresh.
        cf_domain_param_name = f"/contricool/{env_name}/cloudfront-domain"
        cloudfront_domain = ssm.StringParameter.value_for_string_parameter(
            self,
            cf_domain_param_name,
        )
        cors_origins = [
            f"https://{cloudfront_domain}",
            "http://localhost:8081",
            "http://localhost:8082",
            "http://localhost:19006",
        ]

        # API Gateway HTTP API.
        self.api_gateway = apigwv2.HttpApi(
            self,
            "ApiGateway",
            api_name=f"contricool-api-{env_name}",
            description=f"ContriCool API ({env_name})",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_methods=[
                    apigwv2.CorsHttpMethod.GET,
                    apigwv2.CorsHttpMethod.POST,
                    apigwv2.CorsHttpMethod.OPTIONS,
                ],
                allow_origins=cors_origins,
                allow_headers=[
                    "authorization",
                    "content-type",
                    "idempotency-key",
                    "if-match",
                    "x-api-version",
                    # Phase 2c two-token contract (PR #22): /auth/logout
                    # carries the raw access token here for Cognito
                    # GlobalSignOut.  Without this entry the browser's
                    # CORS preflight rejects the header before the
                    # request even reaches the backend.
                    "x-cognito-access-token",
                ],
                allow_credentials=True,
                expose_headers=["x-request-id", "retry-after"],
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
        # We track each route's CfnRoute so the Stage can declare an
        # explicit dependency on the throttled subset (see below): when
        # a stack adds a new route plus a per-route ``RouteSettings``
        # entry referencing it in the same deployment, CloudFormation
        # otherwise updates the Stage before the route exists and
        # rejects the changeset with NotFoundException.
        public_routes_by_key: dict[str, cdk.CfnResource] = {}
        for path in _PUBLIC_AUTH_PATHS:
            created = self.api_gateway.add_routes(
                path=path,
                methods=[apigwv2.HttpMethod.POST],
                integration=integration,
            )
            for route in created:
                cfn_route = route.node.default_child
                assert isinstance(cfn_route, cdk.CfnResource)
                public_routes_by_key[f"POST {path}"] = cfn_route

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

        # Phase 3a — explicit POST /v1/friends/add so per-route throttling
        # can attach.  The remaining /v1/friends/* routes are served by
        # the catch-all ``/{proxy+}`` (already JWT-authed above).
        friends_add_routes = self.api_gateway.add_routes(
            path="/v1/friends/add",
            methods=[apigwv2.HttpMethod.POST],
            integration=integration,
        )
        for route in friends_add_routes:
            cfn_route = route.node.default_child
            assert isinstance(cfn_route, cdk.CfnResource)
            cfn_route.add_property_override("AuthorizerId", cfn_authorizer.ref)
            cfn_route.add_property_override("AuthorizationType", "JWT")
            public_routes_by_key["POST /v1/friends/add"] = cfn_route

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
            # Tie the Stage update to the throttled routes' creation so
            # CloudFormation can't try to apply ``RouteSettings`` before
            # the referenced routes exist. Without this, adding a new
            # throttled route plus its RouteSettings entry in the same
            # deployment fails with "Unable to find Route by key …".
            for route_key in _ROUTE_THROTTLES:
                throttled_route = public_routes_by_key.get(route_key)
                assert throttled_route is not None, (
                    f"throttled route {route_key!r} missing from "
                    f"_PUBLIC_AUTH_PATHS — keep the two lists in sync"
                )
                cfn_default_stage.add_dependency(throttled_route)

        cdk.CfnOutput(
            self,
            "ApiGatewayEndpoint",
            value=self.api_gateway.api_endpoint,
            description=(
                "Internal API Gateway endpoint — used by CloudFront origin only; "
                "do NOT expose this URL in client code (CLAUDE.md red-line 1)."
            ),
        )

