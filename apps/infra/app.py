"""ContriCool — AWS CDK app entrypoint.

Spins up:
- One account-wide ``Contricool-Shared`` stack (OIDC, deploy roles, Budgets,
  CloudTrail, KMS CMK, SNS alerts topic).
- Per-environment stacks (``Contricool-{Dev,Prod}-{Api,Web,Edge,Monitoring}``).

The stacks for ``Data`` and ``Auth`` are intentionally absent until Phase 2 —
adding empty CloudFormation stacks now would only add deploy noise.

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

ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT")
REGION = os.environ.get("CDK_DEFAULT_REGION", "us-west-2")
ALERTS_EMAIL = os.environ.get("CONTRICOOL_ALERTS_EMAIL")
GITHUB_REPO = os.environ.get("CONTRICOOL_GITHUB_REPO", "GanAlps/contricool")

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
# NB: ``snapstart`` is forced off because AWS Lambda does not support
# SnapStart on container-image functions (only zip-packaged Java/Python/.NET).
# Our Phase 1b API ships as an arm64 container image (apps/api/Dockerfile +
# AWS Lambda Web Adapter) so SnapStart is not available. Enabling the flag
# here yields a CFN ``CREATE_FAILED`` with
# "ContainerImage is not supported for SnapStart enabled functions".
# Re-enable once we either (a) switch to a zip-packaged Lambda or (b) AWS
# adds container-image support. Cold-start tax for Python+FastAPI is
# ~500-1500ms, acceptable for MVP traffic with reserved concurrency = 100.
ENV_CONFIGS: dict[str, _EnvConfig] = {
    "dev": {
        "pitr": False,
        "kms_customer_managed": False,
        "log_retention_days": 14,
        "xray_sampling_rate": 1.0,
        "include_dashboard": False,
        "snapstart": False,
    },
    "prod": {
        "pitr": True,
        "kms_customer_managed": True,
        "log_retention_days": 14,
        "xray_sampling_rate": 0.1,
        "include_dashboard": True,
        "snapstart": False,
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

    api = ApiStack(
        app,
        f"Contricool-{suffix}-Api",
        env=cdk_env,
        env_name=env_name,
        snapstart=cfg["snapstart"],
        log_retention_days=cfg["log_retention_days"],
        xray_sampling_rate=cfg["xray_sampling_rate"],
    )

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
    cdk.Tags.of(api).add("env", env_name)
    cdk.Tags.of(web).add("env", env_name)
    cdk.Tags.of(monitoring).add("env", env_name)

# Apply project-wide tag to the whole app (including Shared).
cdk.Tags.of(app).add("app", "contricool")
cdk.Tags.of(shared).add("env", "shared")

# Enforcement aspect — fails synth if a resource violates a red-line guardrail.
cdk.Aspects.of(app).add(SecurityAspect())

app.synth()
