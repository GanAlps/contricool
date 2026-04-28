"""Smoke synth tests — each top-level stack synthesizes without error.

Doesn't assert specific resource shapes (those would be brittle and
duplicate the design docs); instead asserts the app-level synth completes
and produces a non-empty CloudFormation template per stack with a few
shape checks tied to red-line guardrails (Lambda concurrency, S3 block
public access).
"""
from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from stacks.api_stack import ApiStack
from stacks.monitoring_stack import MonitoringStack
from stacks.shared_stack import SharedStack
from stacks.web_stack import WebStack


@pytest.fixture
def cdk_env() -> cdk.Environment:
    return cdk.Environment(account="111111111111", region="us-west-2")


def test_shared_stack_synthesizes(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    stack = SharedStack(
        app,
        "Contricool-Shared",
        env=cdk_env,
        github_repo="GanAlps/contricool",
        alerts_email="ops@example.invalid",
    )
    template = assertions.Template.from_stack(stack)

    # CDK provisions OIDC providers via a Custom resource (it wraps the
    # native CFN type to emit the thumbprint).
    template.resource_count_is("Custom::AWSCDKOpenIdConnectProvider", 1)
    template.resource_count_is("AWS::Budgets::Budget", 1)
    template.resource_count_is("AWS::CloudTrail::Trail", 1)
    # KMS CMK + the SNS topic + CloudTrail log encryption may add extras;
    # assert at least one of each:
    template.resource_count_is("AWS::SNS::Topic", 1)

    # The three named deploy roles exist.
    template.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": "Contricool-CI-Dev-Deploy"},
    )
    template.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": "Contricool-CI-Prod-Deploy"},
    )
    template.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": "Contricool-CI-PR-ReadOnly"},
    )


def test_api_stack_synthesizes(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    stack = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
    )
    template = assertions.Template.from_stack(stack)
    # Lambda has reserved concurrency = 100 (red-line 2).
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"ReservedConcurrentExecutions": 100},
    )
    # Lambda image runs on arm64.
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Architectures": ["arm64"]},
    )
    # API Gateway HTTP API exists.
    template.resource_count_is("AWS::ApiGatewayV2::Api", 1)
    # Lambda alias exists (named "live").
    template.has_resource_properties(
        "AWS::Lambda::Alias",
        {"Name": "live"},
    )


def test_web_stack_synthesizes(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    api = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
    )
    stack = WebStack(
        app,
        "Contricool-Dev-Web",
        env=cdk_env,
        env_name="dev",
        api_gateway=api.api_gateway,
    )
    template = assertions.Template.from_stack(stack)

    # S3 bucket with BlockPublicAccess.BLOCK_ALL (red-line 2).
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        },
    )
    template.resource_count_is("AWS::CloudFront::Distribution", 1)
    template.resource_count_is("AWS::CloudFront::Function", 1)
    template.resource_count_is("AWS::CloudFront::ResponseHeadersPolicy", 1)


def test_monitoring_stack_dev_no_dashboard(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    api = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
    )
    mon = MonitoringStack(
        app,
        "Contricool-Dev-Monitoring",
        env=cdk_env,
        env_name="dev",
        api_lambda_alias=api.lambda_alias,
        api_gateway=api.api_gateway,
        alerts_topic_arn="arn:aws:sns:us-west-2:111111111111:Contricool-Alerts",
        include_dashboard=False,
    )
    template = assertions.Template.from_stack(mon)
    template.resource_count_is("AWS::CloudWatch::Dashboard", 0)
    # Two alarms wired (lambda-errors, apigw-5xx).
    template.resource_count_is("AWS::CloudWatch::Alarm", 2)


def test_monitoring_stack_prod_has_dashboard(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    api = ApiStack(
        app,
        "Contricool-Prod-Api",
        env=cdk_env,
        env_name="prod",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=0.1,
    )
    mon = MonitoringStack(
        app,
        "Contricool-Prod-Monitoring",
        env=cdk_env,
        env_name="prod",
        api_lambda_alias=api.lambda_alias,
        api_gateway=api.api_gateway,
        alerts_topic_arn="arn:aws:sns:us-west-2:111111111111:Contricool-Alerts",
        include_dashboard=True,
    )
    template = assertions.Template.from_stack(mon)
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)
