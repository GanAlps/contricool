"""ContriCool — AWS CDK app entrypoint.

Spins up:
- One account-wide ``Contricool-Shared`` stack (OIDC, deploy roles, Budgets,
  CloudTrail, KMS CMK, SNS alerts topic).
- Per-environment stacks: ``Contricool-{Dev,Prod}-{Api,Web,Auth,Data,Monitoring}``.

``Auth`` and ``Data`` were added in Phase 2a; both stand up empty resources
(Cognito User Pool with no users, DDB Users table with no rows). Phase 2b/2c
wires the API Lambda to read them.

Configuration that varies per environment is read from environment variables
(never hard-coded — see CLAUDE.md red-line 1):

- ``CDK_DEFAULT_ACCOUNT``: AWS account ID (required).
- ``CDK_DEFAULT_REGION``:  AWS region (defaults to ``us-west-2``).
- ``CONTRICOOL_ALERTS_EMAIL``: email subscribed to the alerts SNS topic and
  AWS Budget notifications (required for synth).
- ``CONTRICOOL_GITHUB_REPO``: GitHub repo in ``owner/name`` format (defaults
  to ``GanAlps/contricool`` — public repo, fine to default).
"""
from __future__ import annotations

import os
from typing import TypedDict

import aws_cdk as cdk

from aspects.security_aspect import SecurityAspect
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.monitoring_stack import MonitoringStack
from stacks.shared_stack import SharedStack
from stacks.web_stack import WebStack


class _EnvConfig(TypedDict):
    pitr: bool
    kms_customer_managed: bool
    log_retention_days: int
    xray_sampling_rate: float
    include_dashboard: bool
    snapstart: bool
    api_reserved_concurrency: int

ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT")
REGION = os.environ.get("CDK_DEFAULT_REGION", "us-west-2")
ALERTS_EMAIL = os.environ.get("CONTRICOOL_ALERTS_EMAIL")
GITHUB_REPO = os.environ.get("CONTRICOOL_GITHUB_REPO", "GanAlps/contricool")
# Surfaces in the Lambda's APP_VERSION env var and ``/v1/health`` response.
# deploy.yml exports ${{ github.sha }}; local synth defaults to "dev".
APP_VERSION = os.environ.get("CONTRICOOL_APP_VERSION", "dev")

if not ACCOUNT:
    raise RuntimeError(
        "CDK_DEFAULT_ACCOUNT is unset. Run `aws sts get-caller-identity` "
        "and export CDK_DEFAULT_ACCOUNT before `cdk synth`."
    )
if not ALERTS_EMAIL:
    raise RuntimeError(
        "CONTRICOOL_ALERTS_EMAIL is unset. Set it to the email address that "
        "should receive AWS Budget warnings and CloudWatch alarms."
    )

app = cdk.App()
cdk_env = cdk.Environment(account=ACCOUNT, region=REGION)

# Per-environment configuration. Values are deliberate; see
# specs/03-hosting-infrastructure/design.md.
# NB1: ``snapstart`` is forced off because AWS Lambda does not support
# SnapStart on container-image functions (only zip-packaged Java/Python/.NET).
# Our Phase 1b API ships as an arm64 container image (apps/api/Dockerfile +
# AWS Lambda Web Adapter) so SnapStart is not available. Enabling the flag
# here yields a CFN ``CREATE_FAILED`` with
# "ContainerImage is not supported for SnapStart enabled functions".
# Re-enable once we either (a) switch to a zip-packaged Lambda or (b) AWS
# adds container-image support. Cold-start tax for Python+FastAPI is
# ~500-1500ms, acceptable for MVP traffic with reserved concurrency.
#
# NB2: ``api_reserved_concurrency`` is 5 in dev (solo-dev traffic) and 100
# in prod. Brand-new AWS accounts default to a Lambda Concurrent-Executions
# account quota of 10, which makes reserved=100 unattainable on either env
# until the quota is raised. Solo dev only ever runs one or two requests
# at a time, so 5 is plenty and leaves 5 unreserved for CDK-internal
# provider Lambdas (BucketDeployment, OIDC thumbprint, etc.). Prod stays
# at 100 per CLAUDE.md red-line 2; the prod deploy gate will fail until
# the account quota is raised, which is the right behaviour (forces the
# operator to raise the quota before exposing prod traffic).
ENV_CONFIGS: dict[str, _EnvConfig] = {
    "dev": {
        "pitr": False,
        "kms_customer_managed": False,
        "log_retention_days": 14,
        "xray_sampling_rate": 1.0,
        "include_dashboard": False,
        "snapstart": False,
        "api_reserved_concurrency": 5,
    },
    "prod": {
        "pitr": True,
        "kms_customer_managed": True,
        "log_retention_days": 14,
        "xray_sampling_rate": 0.1,
        "include_dashboard": True,
        "snapstart": False,
        "api_reserved_concurrency": 100,
    },
}

# Account-wide shared stack — OIDC provider, deploy roles, Budgets,
# CloudTrail, KMS CMK, SNS alerts topic.
shared = SharedStack(
    app,
    "Contricool-Shared",
    env=cdk_env,
    github_repo=GITHUB_REPO,
    alerts_email=ALERTS_EMAIL,
)

# Per-environment stacks.
for env_name, cfg in ENV_CONFIGS.items():
    suffix = env_name.capitalize()  # "Dev" or "Prod"
    is_prod = env_name == "prod"
    prod_cmk_arn = shared.prod_cmk.key_arn if is_prod else None

    auth = AuthStack(
        app,
        f"Contricool-{suffix}-Auth",
        env=cdk_env,
        env_name=env_name,
        prod_cmk_arn=prod_cmk_arn,
    )
    auth.add_dependency(shared)

    data = DataStack(
        app,
        f"Contricool-{suffix}-Data",
        env=cdk_env,
        env_name=env_name,
        prod_cmk=shared.prod_cmk if is_prod else None,
    )
    data.add_dependency(shared)

    api = ApiStack(
        app,
        f"Contricool-{suffix}-Api",
        env=cdk_env,
        env_name=env_name,
        snapstart=cfg["snapstart"],
        log_retention_days=cfg["log_retention_days"],
        xray_sampling_rate=cfg["xray_sampling_rate"],
        reserved_concurrent_executions=cfg["api_reserved_concurrency"],
        prod_cmk=shared.prod_cmk if is_prod else None,
        app_version=APP_VERSION,
    )
    api.add_dependency(shared)

    web = WebStack(
        app,
        f"Contricool-{suffix}-Web",
        env=cdk_env,
        env_name=env_name,
        api_gateway=api.api_gateway,
    )
    web.add_dependency(api)

    monitoring = MonitoringStack(
        app,
        f"Contricool-{suffix}-Monitoring",
        env=cdk_env,
        env_name=env_name,
        api_lambda_alias=api.lambda_alias,
        api_gateway=api.api_gateway,
        alerts_topic_arn=shared.alerts_topic.topic_arn,
        include_dashboard=cfg["include_dashboard"],
    )
    monitoring.add_dependency(api)

    # Apply per-env tag to every resource in per-env stacks.
    cdk.Tags.of(auth).add("env", env_name)
    cdk.Tags.of(data).add("env", env_name)
    cdk.Tags.of(api).add("env", env_name)
    cdk.Tags.of(web).add("env", env_name)
    cdk.Tags.of(monitoring).add("env", env_name)

# Apply project-wide tag to the whole app (including Shared).
cdk.Tags.of(app).add("app", "contricool")
cdk.Tags.of(shared).add("env", "shared")

# Enforcement aspect — fails synth if a resource violates a red-line guardrail.
cdk.Aspects.of(app).add(SecurityAspect())

app.synth()
