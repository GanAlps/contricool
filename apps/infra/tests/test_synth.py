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


def test_alerts_topic_uses_aws_managed_encryption(cdk_env: cdk.Environment) -> None:
    """Alerts topic must NOT specify a CMK — that path silently breaks publishes
    from CloudWatch / Budgets / SNS without explicit key-policy grants. AWS-managed
    SNS encryption is sufficient for operational alarm metadata at MVP."""
    import json

    app = cdk.App()
    stack = SharedStack(
        app,
        "Contricool-Shared",
        env=cdk_env,
        github_repo="GanAlps/contricool",
        alerts_email="ops@example.invalid",
    )
    template = assertions.Template.from_stack(stack)
    topics = template.find_resources("AWS::SNS::Topic")
    alerts = [
        props
        for props in topics.values()
        if props["Properties"].get("TopicName") == "Contricool-Alerts"
    ]
    assert len(alerts) == 1, "Expected exactly one Contricool-Alerts topic"
    props = alerts[0]["Properties"]
    assert "KmsMasterKeyId" not in props, (
        "Alerts topic must not be CMK-encrypted at MVP; "
        f"got KmsMasterKeyId={props.get('KmsMasterKeyId')!r}. "
        "See shared_stack.py comment on the alerts_topic block."
    )
    # Belt-and-braces: no key policy in the rendered template should grant
    # cloudwatch.amazonaws.com (we removed the dependency, so the principal
    # shouldn't appear); inverse asserts both the topic AND the key policy
    # stay in sync.
    keys = template.find_resources("AWS::KMS::Key")
    for key_props in keys.values():
        statements = key_props["Properties"]["KeyPolicy"]["Statement"]
        principals = json.dumps(statements)
        assert "cloudwatch.amazonaws.com" not in principals, (
            "KMS key policy unexpectedly grants cloudwatch — if this is intentional, "
            "re-attach the CMK to the alerts topic and update this test."
        )


def test_dev_deploy_role_cannot_write_shared_stack(cdk_env: cdk.Environment) -> None:
    """The dev deploy role must not be able to UpdateStack on Contricool-Shared.
    Shared owns the prod role's trust policy — dev write access is a privilege-
    escalation path to prod."""
    import json

    app = cdk.App()
    stack = SharedStack(
        app,
        "Contricool-Shared",
        env=cdk_env,
        github_repo="GanAlps/contricool",
        alerts_email="ops@example.invalid",
    )
    template = assertions.Template.from_stack(stack)

    # First locate the dev deploy role's logical ID.
    roles = template.find_resources("AWS::IAM::Role")
    dev_role_logical_id: str | None = None
    for logical_id, props in roles.items():
        if props["Properties"].get("RoleName") == "Contricool-CI-Dev-Deploy":
            dev_role_logical_id = logical_id
            break
    assert dev_role_logical_id, "Could not locate dev deploy role"

    # Then find inline policies attached to it via Ref.
    policies = template.find_resources("AWS::IAM::Policy")
    dev_policies = [
        props
        for props in policies.values()
        if any(
            isinstance(role, dict) and role.get("Ref") == dev_role_logical_id
            for role in props["Properties"].get("Roles", [])
        )
    ]
    assert dev_policies, "Could not locate dev deploy role's inline policy"

    write_actions = {
        "cloudformation:UpdateStack",
        "cloudformation:CreateChangeSet",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:CreateStack",
        "cloudformation:DeleteStack",
        "cloudformation:DeleteChangeSet",
        "cloudformation:RollbackStack",
        "cloudformation:ContinueUpdateRollback",
    }
    for props in dev_policies:
        statements = props["Properties"]["PolicyDocument"]["Statement"]
        for stmt in statements:
            actions = stmt.get("Action", [])
            actions = [actions] if isinstance(actions, str) else actions
            resources = stmt.get("Resource", [])
            resources = [resources] if isinstance(resources, str) else resources
            if any(a in write_actions for a in actions):
                blob = json.dumps(resources)
                assert "Shared" not in blob, (
                    f"Dev role grants CFN write on a Shared resource: {blob}"
                )


def test_deploy_role_trust_patterns_match_workflow_environment_keys(
    cdk_env: cdk.Environment,
) -> None:
    """Both deploy roles must trust ``:environment:<env>`` sub claims, not
    ``:ref:refs/heads/main``. ``deploy.yml`` declares ``environment: dev``
    and ``environment: prod`` on the per-env jobs; GitHub's OIDC ``sub``
    claim takes the form ``repo:OWNER/REPO:environment:<env>`` whenever a
    job has an ``environment:`` key. A ``ref:`` trust would fail with
    ``Not authorized to perform sts:AssumeRoleWithWebIdentity`` even
    though the merge to main is exactly what triggered the workflow."""
    import json

    app = cdk.App()
    stack = SharedStack(
        app,
        "Contricool-Shared",
        env=cdk_env,
        github_repo="GanAlps/contricool",
        alerts_email="ops@example.invalid",
    )
    template = assertions.Template.from_stack(stack)
    roles = template.find_resources("AWS::IAM::Role")

    expected_subs = {
        "Contricool-CI-Dev-Deploy": "repo:GanAlps/contricool:environment:dev",
        "Contricool-CI-Prod-Deploy": "repo:GanAlps/contricool:environment:prod",
    }
    seen: dict[str, bool] = {name: False for name in expected_subs}

    for props in roles.values():
        role_name = props["Properties"].get("RoleName")
        if role_name not in expected_subs:
            continue
        trust = props["Properties"]["AssumeRolePolicyDocument"]
        statements = trust["Statement"]
        # Each role has exactly one OIDC trust statement.
        assert len(statements) == 1, (
            f"{role_name} has {len(statements)} trust statements; "
            f"expected exactly 1: {json.dumps(statements)}"
        )
        condition = statements[0].get("Condition", {})
        sub_pattern = (
            condition.get("StringLike", {}).get("token.actions.githubusercontent.com:sub")
        )
        assert sub_pattern == expected_subs[role_name], (
            f"{role_name}: trust ``sub`` is {sub_pattern!r}, "
            f"expected {expected_subs[role_name]!r}. A ``ref:`` trust "
            f"will reject the OIDC token from a job that declares "
            f"``environment:`` because GitHub emits ``:environment:<env>`` "
            f"in the sub claim, not ``:ref:refs/heads/main``."
        )
        seen[role_name] = True

    missing = [name for name, found in seen.items() if not found]
    assert not missing, f"Could not locate trust on roles: {missing}"


def test_pr_readonly_role_does_not_use_managed_readonly_access(
    cdk_env: cdk.Environment,
) -> None:
    """PR-readonly must use a hand-rolled minimum surface, not the AWS-managed
    ReadOnlyAccess policy (which includes secretsmanager:GetSecretValue)."""
    app = cdk.App()
    stack = SharedStack(
        app,
        "Contricool-Shared",
        env=cdk_env,
        github_repo="GanAlps/contricool",
        alerts_email="ops@example.invalid",
    )
    template = assertions.Template.from_stack(stack)
    roles = template.find_resources("AWS::IAM::Role")
    pr_roles = [
        props
        for props in roles.values()
        if props["Properties"].get("RoleName") == "Contricool-CI-PR-ReadOnly"
    ]
    assert len(pr_roles) == 1
    managed = pr_roles[0]["Properties"].get("ManagedPolicyArns", [])
    for arn in managed:
        assert "ReadOnlyAccess" not in str(arn), (
            f"PR-readonly role must not attach ReadOnlyAccess; got {arn!r}"
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
