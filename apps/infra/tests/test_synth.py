"""Smoke synth tests — each top-level stack synthesizes without error.

Doesn't assert specific resource shapes (those would be brittle and
duplicate the design docs); instead asserts the app-level synth completes
and produces a non-empty CloudFormation template per stack with a few
shape checks tied to red-line guardrails (Lambda concurrency, S3 block
public access).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.monitoring_stack import MonitoringStack
from stacks.shared_stack import SharedStack
from stacks.web_stack import WebStack

# Phase 2e: synth tests use a tiny placeholder bundle so they don't
# depend on `pnpm --filter @contricool/client build:web` having run.
_WEB_BUNDLE_FIXTURE = str(Path(__file__).parent / "fixtures" / "web-bundle")


@pytest.fixture
def cdk_env() -> cdk.Environment:
    return cdk.Environment(account="111111111111", region="us-west-2")


def _api_stack_auth_data_kwargs(
    app: cdk.App, cdk_env: cdk.Environment, *, env_name: str
) -> dict[str, object]:
    """Build the per-env Auth + Data stacks + return kwargs for ApiStack.

    Phase 2c made ``user_pool``, ``web_client``, ``ios_client``,
    ``android_client``, and ``users_table`` required parameters on
    :class:`ApiStack`. Synth tests build the upstream stacks here so
    they can inject real (unsynthesized) ``IUserPool`` / ``ITable``
    handles.
    """
    from aws_cdk import aws_kms as kms

    is_prod = env_name == "prod"
    cmk_for_data = None
    if is_prod:
        cmk_scope = cdk.Stack(app, f"CmkScopeForApi-{env_name}", env=cdk_env)
        cmk_for_data = kms.Key.from_key_arn(
            cmk_scope,
            "FakeCmk",
            f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}",
        )
    auth = AuthStack(
        app,
        f"AuthForApiTest-{env_name}",
        env=cdk_env,
        env_name=env_name,
        prod_cmk_arn=(
            f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}"
            if is_prod
            else None
        ),
    )
    data = DataStack(
        app,
        f"DataForApiTest-{env_name}",
        env=cdk_env,
        env_name=env_name,
        prod_cmk=cmk_for_data,
    )
    return {
        "user_pool": auth.user_pool,
        "web_client": auth.web_client,
        "ios_client": auth.ios_client,
        "android_client": auth.android_client,
        "users_table": data.users_table,
        "transactions_table": data.transactions_table,
    }


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


def test_deploy_roles_explicitly_deny_writes_to_pii_salt(
    cdk_env: cdk.Environment,
) -> None:
    """Deploy roles need ``ssm:PutParameter`` on the wildcard
    ``/contricool/*`` path so deploy.yml can publish CloudFront domains,
    Cognito IDs, and table names. An explicit Deny on
    ``/contricool/*/pii-salt`` ensures the pii-salt SSM SecureString stays
    owned exclusively by the AuthStack custom resource — rotation breaks
    every email lookup row, so the IAM layer enforces the no-rotation rule
    that ``test_deploy_yaml_writes_cognito_and_ddb_ids_to_ssm`` only
    enforces in the workflow text."""
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
    deploy_role_ids = [
        logical_id
        for logical_id, props in roles.items()
        if props["Properties"].get("RoleName")
        in ("Contricool-CI-Dev-Deploy", "Contricool-CI-Prod-Deploy")
    ]
    assert len(deploy_role_ids) == 2, "Expected dev + prod deploy roles"

    policies = template.find_resources("AWS::IAM::Policy")
    for role_id in deploy_role_ids:
        # Find the inline policy attached to this role.
        attached = [
            props
            for props in policies.values()
            if any(
                isinstance(r, dict) and r.get("Ref") == role_id
                for r in props["Properties"].get("Roles", [])
            )
        ]
        assert attached, f"No inline policy attached to {role_id}"

        # Aggregate every statement across attached policies.
        deny_statements: list[dict[str, object]] = []
        for props in attached:
            for stmt in props["Properties"]["PolicyDocument"]["Statement"]:
                if stmt.get("Effect") == "Deny":
                    deny_statements.append(stmt)

        # Some statement must Deny PutParameter on the pii-salt path.
        salt_denies = [
            s
            for s in deny_statements
            if "ssm:PutParameter" in (
                s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            )
            and "pii-salt" in json.dumps(s.get("Resource", ""))
        ]
        assert salt_denies, (
            f"Role {role_id}: no Deny on ssm:PutParameter for "
            "/contricool/*/pii-salt. Without this, the wildcard "
            "PutParameter Allow on /contricool/* could overwrite the salt."
        )
        # And DeleteParameter, for symmetry.
        salt_delete_denies = [
            s
            for s in deny_statements
            if "ssm:DeleteParameter" in (
                s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            )
            and "pii-salt" in json.dumps(s.get("Resource", ""))
        ]
        assert salt_delete_denies, (
            f"Role {role_id}: no Deny on ssm:DeleteParameter for the salt path."
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
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="dev"),
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


def test_api_stack_lambda_can_read_ssm_for_cold_start_config(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 2b's ``app.core.config.load`` calls ``ssm:GetParameters`` at
    cold start. Without an IAM grant the Lambda fails to start with
    AccessDenied. Lock the grant + scope so a future refactor can't
    drop it silently."""
    import json

    app = cdk.App()
    stack = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=False,
        log_retention_days=14,
        xray_sampling_rate=1.0,
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="dev"),
    )
    template = assertions.Template.from_stack(stack)
    policies = template.find_resources("AWS::IAM::Policy")
    blob = json.dumps(list(policies.values()))
    assert "ssm:GetParameters" in blob, (
        "ApiStack must grant ssm:GetParameters to the Lambda role"
    )
    assert "parameter/contricool/dev/" in blob, (
        "SSM grant must be scoped to /contricool/<env>/* — "
        "wildcard SSM read would let the function dump every parameter"
    )


def test_api_stack_prod_lambda_can_decrypt_pii_salt(
    cdk_env: cdk.Environment,
) -> None:
    """Prod's pii-salt is encrypted with the project CMK; the Lambda must
    have ``kms:Decrypt`` to read the SecureString back. Dev uses
    ``alias/aws/ssm`` so no explicit grant is needed there."""
    import json

    from aws_cdk import aws_kms as kms

    app = cdk.App()
    cmk_scope = cdk.Stack(app, "CmkScope", env=cdk_env)
    cmk = kms.Key.from_key_arn(
        cmk_scope,
        "Cmk",
        f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}",
    )
    stack = ApiStack(
        app,
        "Contricool-Prod-Api",
        env=cdk_env,
        env_name="prod",
        snapstart=False,
        log_retention_days=14,
        xray_sampling_rate=0.1,
        prod_cmk=cmk,
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="prod"),
    )
    template = assertions.Template.from_stack(stack)
    policies = template.find_resources("AWS::IAM::Policy")
    blob = json.dumps(list(policies.values()))
    assert "kms:Decrypt" in blob, (
        "Prod ApiStack must grant kms:Decrypt for the SecureString PII salt"
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
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="dev"),
    )
    stack = WebStack(
        app,
        "Contricool-Dev-Web",
        env=cdk_env,
        env_name="dev",
        api_gateway=api.api_gateway,
        bundle_source_path=_WEB_BUNDLE_FIXTURE,
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


def test_web_stack_csp_goes_through_security_headers_not_custom_headers(
    cdk_env: cdk.Environment,
) -> None:
    """CloudFront rejects Content-Security-Policy as a custom header at
    deploy time with ``is a security header and cannot be set as custom
    header``. CSP (and HSTS, X-Frame-Options, X-Content-Type-Options,
    Referrer-Policy, X-XSS-Protection) must be set via
    ``security_headers_behavior``. Permissions-Policy is NOT on this list
    so it stays in ``custom_headers_behavior``."""
    app = cdk.App()
    api = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="dev"),
    )
    stack = WebStack(
        app,
        "Contricool-Dev-Web",
        env=cdk_env,
        env_name="dev",
        api_gateway=api.api_gateway,
        bundle_source_path=_WEB_BUNDLE_FIXTURE,
    )
    template = assertions.Template.from_stack(stack)
    policies = template.find_resources("AWS::CloudFront::ResponseHeadersPolicy")
    assert len(policies) == 1
    config = next(iter(policies.values()))["Properties"]["ResponseHeadersPolicyConfig"]

    # CSP belongs in SecurityHeadersConfig.
    csp = config.get("SecurityHeadersConfig", {}).get("ContentSecurityPolicy")
    assert csp is not None, (
        "CSP must be set via security_headers_behavior.content_security_policy; "
        "putting it in custom_headers_behavior makes CloudFront reject the "
        "policy at deploy time."
    )
    assert "default-src" in csp.get("ContentSecurityPolicy", "")

    # Reserved security headers MUST NOT appear in custom_headers.
    custom_items = (
        config.get("CustomHeadersConfig", {}).get("Items", [])
    )
    custom_header_names = {item["Header"] for item in custom_items}
    reserved = {
        "Content-Security-Policy",
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "X-XSS-Protection",
    }
    overlap = custom_header_names & reserved
    assert not overlap, (
        f"Reserved security headers found in custom_headers: {overlap!r}. "
        "CloudFront rejects these at deploy time."
    )


def test_monitoring_stack_dev_no_dashboard(cdk_env: cdk.Environment) -> None:
    app = cdk.App()
    api_kwargs = _api_stack_auth_data_kwargs(app, cdk_env, env_name="dev")
    api = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
        **api_kwargs,
    )
    mon = MonitoringStack(
        app,
        "Contricool-Dev-Monitoring",
        env=cdk_env,
        env_name="dev",
        api_lambda_alias=api.lambda_alias,
        api_gateway=api.api_gateway,
        users_table=api_kwargs["users_table"],  # type: ignore[arg-type]
        transactions_table=api_kwargs["transactions_table"],  # type: ignore[arg-type]
        alerts_topic_arn="arn:aws:sns:us-west-2:111111111111:Contricool-Alerts",
        include_dashboard=False,
    )
    template = assertions.Template.from_stack(mon)
    template.resource_count_is("AWS::CloudWatch::Dashboard", 0)
    # Phase 6: 7 simple alarms (lambda-errors, lambda-throttles,
    # lambda-duration-p95, apigw-5xx, apigw-4xx-burst,
    # ddb-throttle-users, ddb-throttle-transactions) + 1 composite.
    template.resource_count_is("AWS::CloudWatch::Alarm", 7)
    template.resource_count_is("AWS::CloudWatch::CompositeAlarm", 1)
    # Saved Logs Insights queries (one per row in _SAVED_QUERIES).
    template.resource_count_is("AWS::Logs::QueryDefinition", 6)


def _auth_stack(env_name: str, cdk_env: cdk.Environment) -> assertions.Template:
    app = cdk.App()
    stack = AuthStack(
        app,
        f"Contricool-{env_name.capitalize()}-Auth",
        env=cdk_env,
        env_name=env_name,
        prod_cmk_arn=(
            f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}"
            if env_name == "prod"
            else None
        ),
    )
    return assertions.Template.from_stack(stack)


def _data_stack(env_name: str, cdk_env: cdk.Environment) -> assertions.Template:
    import aws_cdk as cdk_mod
    from aws_cdk import aws_kms as kms

    app = cdk_mod.App()
    fake_cmk_stack = cdk_mod.Stack(app, "FakeCmkScope", env=cdk_env)
    cmk = (
        kms.Key.from_key_arn(
            fake_cmk_stack,
            "FakeCmk",
            f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}",
        )
        if env_name == "prod"
        else None
    )
    stack = DataStack(
        app,
        f"Contricool-{env_name.capitalize()}-Data",
        env=cdk_env,
        env_name=env_name,
        prod_cmk=cmk,
    )
    return assertions.Template.from_stack(stack)


def test_auth_stack_user_pool_email_only_no_sms_no_mfa(
    cdk_env: cdk.Environment,
) -> None:
    """Pool must verify email (only), be MfaConfiguration=OFF, and carry NO
    SmsConfiguration / SnsCallerArn (Design 4 + CONSTRAINTS.md §4)."""
    template = _auth_stack("dev", cdk_env)
    pools = template.find_resources("AWS::Cognito::UserPool")
    assert len(pools) == 1
    props = next(iter(pools.values()))["Properties"]
    assert props["MfaConfiguration"] == "OFF"
    assert props["AutoVerifiedAttributes"] == ["email"]
    assert "SmsConfiguration" not in props
    assert "SmsAuthenticationMessage" not in props
    # Username attribute is email; sign-in is email-based.
    assert "email" in props["UsernameAttributes"]


def test_auth_stack_password_policy_meets_design_4(
    cdk_env: cdk.Environment,
) -> None:
    """Min 10, all four classes required, history 3."""
    template = _auth_stack("dev", cdk_env)
    pool_props = next(iter(template.find_resources("AWS::Cognito::UserPool").values()))[
        "Properties"
    ]
    policy = pool_props["Policies"]["PasswordPolicy"]
    assert policy["MinimumLength"] == 10
    assert policy["RequireLowercase"] is True
    assert policy["RequireUppercase"] is True
    assert policy["RequireNumbers"] is True
    assert policy["RequireSymbols"] is True
    assert policy["PasswordHistorySize"] == 3


def test_auth_stack_custom_user_id_attribute(cdk_env: cdk.Environment) -> None:
    """Exactly one custom attribute: ``user_id`` (ULID, len 26, immutable)."""
    template = _auth_stack("dev", cdk_env)
    pool_props = next(iter(template.find_resources("AWS::Cognito::UserPool").values()))[
        "Properties"
    ]
    schema = pool_props["Schema"]
    custom = [s for s in schema if s["Name"].startswith("user_id") or s.get("Name") == "user_id"]
    # Cognito reports custom attrs with their bare Name (no "custom:" prefix in schema).
    assert len(custom) == 1, f"Expected one custom attribute; got {custom!r}"
    cu = custom[0]
    assert cu["AttributeDataType"] == "String"
    assert cu.get("Mutable") in (False, None) or cu["Mutable"] is False
    constraints = cu.get("StringAttributeConstraints", {})
    assert constraints.get("MinLength") == "26"
    assert constraints.get("MaxLength") == "26"


def test_auth_stack_three_clients_no_secret_with_mvp_flows(
    cdk_env: cdk.Environment,
) -> None:
    """Three app clients (web/ios/android), all public (no secret), with
    the MVP flow set: USER_SRP_AUTH + USER_PASSWORD_AUTH + REFRESH_TOKEN_AUTH.

    USER_PASSWORD_AUTH is the MVP server-side login path per
    ``specs/phase-2c-auth-feature/design.md`` Trade-off 1: at MVP the
    web client posts plain JSON to the backend and the backend calls
    ``InitiateAuth(USER_PASSWORD_AUTH)``. Phase 2d swaps the client to
    Amplify SRP — both flows must coexist so the transition needs no
    Cognito changes. ``ADMIN_USER_PASSWORD_AUTH`` stays forbidden; it
    bypasses Cognito client validation entirely and is not used by the
    backend."""
    template = _auth_stack("dev", cdk_env)
    clients = template.find_resources("AWS::Cognito::UserPoolClient")
    assert len(clients) == 3
    names = {c["Properties"]["ClientName"] for c in clients.values()}
    assert names == {"web", "ios", "android"}
    for c in clients.values():
        props = c["Properties"]
        assert props.get("GenerateSecret") in (False, None)
        flows = set(props.get("ExplicitAuthFlows", []))
        # CDK expands user_srp=True / user_password=True into the matching
        # ALLOW_* tokens plus ALLOW_REFRESH_TOKEN_AUTH (always-on framework
        # helper). All three are required at MVP.
        assert "ALLOW_USER_SRP_AUTH" in flows
        assert "ALLOW_USER_PASSWORD_AUTH" in flows
        assert "ALLOW_REFRESH_TOKEN_AUTH" in flows
        # Admin flows MUST NOT be enabled — they bypass client validation.
        forbidden = {
            "ALLOW_ADMIN_USER_PASSWORD_AUTH",
            "ALLOW_CUSTOM_AUTH",
        }
        assert not (flows & forbidden), (
            f"Client {props['ClientName']} has forbidden flows: {flows & forbidden!r}"
        )


def test_auth_stack_clients_have_no_oauth_flows(
    cdk_env: cdk.Environment,
) -> None:
    """``AllowedOAuthFlows`` must be empty on every client. CDK's default
    when ``o_auth=`` is omitted is to enable ``code`` + ``implicit`` with
    a placeholder callback URL — not what we want at MVP (federation
    deferred). Asserting here catches the regression where someone
    deletes the explicit ``OAuthSettings`` block."""
    template = _auth_stack("dev", cdk_env)
    clients = template.find_resources("AWS::Cognito::UserPoolClient")
    for c in clients.values():
        props = c["Properties"]
        flows = props.get("AllowedOAuthFlows") or []
        assert not flows, (
            f"Client {props['ClientName']} has OAuth flows enabled: {flows!r}; "
            "MVP requires AllowedOAuthFlows be empty."
        )
        # AllowedOAuthFlowsUserPoolClient must be False/missing — when True it
        # opts the client into the OAuth flows above.
        assert props.get("AllowedOAuthFlowsUserPoolClient") in (False, None)
        # Callback / logout URLs must be absent — they have no purpose without
        # OAuth flows.
        assert not props.get("CallbackURLs"), (
            f"Client {props['ClientName']} has CallbackURLs set; "
            "remove with OAuth flows."
        )
        assert not props.get("LogoutURLs"), (
            f"Client {props['ClientName']} has LogoutURLs set; "
            "remove with OAuth flows."
        )


def test_auth_stack_token_lifetimes_match_design_4(
    cdk_env: cdk.Environment,
) -> None:
    """Access + ID token = 1h, refresh = 30d (Design 4).

    CDK normalises `Duration.hours(1)` to whichever Cognito-supported unit
    fits; we assert in seconds rather than couple to the chosen unit so a
    future CDK rev that picks ``hours`` doesn't break this test.
    """
    template = _auth_stack("dev", cdk_env)
    clients = template.find_resources("AWS::Cognito::UserPoolClient")
    unit_to_seconds = {
        "seconds": 1,
        "minutes": 60,
        "hours": 60 * 60,
        "days": 24 * 60 * 60,
    }
    for c in clients.values():
        props = c["Properties"]
        units = props.get("TokenValidityUnits", {})

        access_seconds = props["AccessTokenValidity"] * unit_to_seconds[units["AccessToken"]]
        id_seconds = props["IdTokenValidity"] * unit_to_seconds[units["IdToken"]]
        refresh_seconds = (
            props["RefreshTokenValidity"] * unit_to_seconds[units["RefreshToken"]]
        )

        assert access_seconds == 60 * 60, f"access != 1h: {access_seconds}s"
        assert id_seconds == 60 * 60, f"id != 1h: {id_seconds}s"
        assert refresh_seconds == 30 * 24 * 60 * 60, (
            f"refresh != 30d: {refresh_seconds}s"
        )

        assert props.get("EnableTokenRevocation") is True
        assert props.get("PreventUserExistenceErrors") == "ENABLED"


def test_auth_stack_pii_salt_provider_kms_in_prod_only(
    cdk_env: cdk.Environment,
) -> None:
    """The PII-salt provider Lambda's IAM policy carries the prod CMK in
    prod and not in dev. Salt parameter path is /contricool/<env>/pii-salt."""
    import json

    dev_template = _auth_stack("dev", cdk_env)
    prod_template = _auth_stack("prod", cdk_env)

    def _policies_text(template: assertions.Template) -> str:
        policies = template.find_resources("AWS::IAM::Policy")
        return json.dumps(list(policies.values()))

    dev_blob = _policies_text(dev_template)
    prod_blob = _policies_text(prod_template)

    assert "/contricool/dev/pii-salt" in dev_blob
    assert "/contricool/prod/pii-salt" in prod_blob

    # CMK actions only appear in prod.
    assert "kms:Encrypt" in prod_blob
    assert "kms:Encrypt" not in dev_blob

    # No DeleteParameter in either env (salt is permanent).
    assert "ssm:DeleteParameter" not in dev_blob
    assert "ssm:DeleteParameter" not in prod_blob


def test_auth_stack_user_pool_retention_in_prod_destroy_in_dev(
    cdk_env: cdk.Environment,
) -> None:
    dev_template = _auth_stack("dev", cdk_env)
    prod_template = _auth_stack("prod", cdk_env)
    dev_pool = next(iter(dev_template.find_resources("AWS::Cognito::UserPool").values()))
    prod_pool = next(
        iter(prod_template.find_resources("AWS::Cognito::UserPool").values())
    )
    assert dev_pool.get("DeletionPolicy") == "Delete"
    assert prod_pool.get("DeletionPolicy") == "Retain"
    # Prod also has DeletionProtection=ACTIVE.
    assert prod_pool["Properties"].get("DeletionProtection") == "ACTIVE"
    assert dev_pool["Properties"].get("DeletionProtection") in (None, "INACTIVE")


def test_auth_stack_email_config_matches_cognito_regex(
    cdk_env: cdk.Environment,
) -> None:
    """Cognito's API rejects ``ReplyToEmailAddress`` values that don't
    match ``[\\p{L}\\p{M}\\p{S}\\p{N}\\p{P}]+@[\\p{L}\\p{M}\\p{S}\\p{N}\\p{P}]+``
    — no spaces, no ``<>`` display-name wrapper. Lock the rule in synth
    so any future ``with_cognito("Friendly <addr>")`` regresses here
    rather than at CFN-create time on a real deploy."""
    import re

    template = _auth_stack("dev", cdk_env)
    pool_props = next(iter(template.find_resources("AWS::Cognito::UserPool").values()))[
        "Properties"
    ]
    email_config = pool_props.get("EmailConfiguration") or {}
    reply_to = email_config.get("ReplyToEmailAddress")
    if reply_to is not None:
        # Equivalent of Cognito's regex (Python ``re`` does not natively
        # support \\p{} character properties, so we approximate with the
        # narrow subset of characters Cognito accepts that we care about).
        assert re.fullmatch(r"[^\s<>]+@[^\s<>]+", reply_to), (
            f"ReplyToEmailAddress {reply_to!r} would be rejected by "
            f"Cognito's regex constraint."
        )
        # And specifically reject the 'Friendly <email>' shape.
        assert "<" not in reply_to and ">" not in reply_to, (
            "ReplyToEmailAddress must not carry a display-name wrapper. "
            "The Cognito-managed sender's friendly From name is fixed by "
            "AWS and cannot be overridden via the reply-to field."
        )


def test_auth_stack_account_recovery_email_only(cdk_env: cdk.Environment) -> None:
    template = _auth_stack("dev", cdk_env)
    pool_props = next(iter(template.find_resources("AWS::Cognito::UserPool").values()))[
        "Properties"
    ]
    recovery = pool_props["AccountRecoverySetting"]["RecoveryMechanisms"]
    names = {r["Name"] for r in recovery}
    assert names == {"verified_email"}, (
        f"Account recovery must be email-only; got {names!r}"
    )


def _find_table(
    template: assertions.Template, table_name: str
) -> Any:
    """Return the synthesised resource dict for a table looked up by name.

    With Phase 4a the Data stack synthesises two tables, so picking via
    ``next(iter(...))`` is non-deterministic. Always go through this helper.
    """
    for resource in template.find_resources("AWS::DynamoDB::Table").values():
        if resource["Properties"].get("TableName") == table_name:
            return resource
    raise AssertionError(
        f"No AWS::DynamoDB::Table resource with TableName={table_name!r} in template"
    )


# ---- Phase 2a — Users table -------------------------------------------


def test_data_stack_users_table_keys_billing_ttl(cdk_env: cdk.Environment) -> None:
    template = _data_stack("dev", cdk_env)
    props = _find_table(template, "ContriCool-Users-dev")["Properties"]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    keys = {k["AttributeName"]: k["KeyType"] for k in props["KeySchema"]}
    assert keys == {"PK": "HASH", "SK": "RANGE"}
    attrs = {a["AttributeName"]: a["AttributeType"] for a in props["AttributeDefinitions"]}
    assert attrs == {
        "PK": "S",
        "SK": "S",
        "GSI1PK": "S",
        "GSI1SK": "S",
    }
    ttl = props["TimeToLiveSpecification"]
    assert ttl["AttributeName"] == "ttl"
    assert ttl["Enabled"] is True


def test_data_stack_users_gsi1_keys_and_projection_all(
    cdk_env: cdk.Environment,
) -> None:
    template = _data_stack("dev", cdk_env)
    props = _find_table(template, "ContriCool-Users-dev")["Properties"]
    gsis = props["GlobalSecondaryIndexes"]
    assert len(gsis) == 1
    gsi1 = gsis[0]
    assert gsi1["IndexName"] == "GSI1"
    assert {k["AttributeName"]: k["KeyType"] for k in gsi1["KeySchema"]} == {
        "GSI1PK": "HASH",
        "GSI1SK": "RANGE",
    }
    assert gsi1["Projection"]["ProjectionType"] == "ALL"


def test_data_stack_users_pitr_streams_only_in_prod(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(_data_stack("dev", cdk_env), "ContriCool-Users-dev")[
        "Properties"
    ]
    prod = _find_table(_data_stack("prod", cdk_env), "ContriCool-Users-prod")[
        "Properties"
    ]
    # Dev: PITR off, no Stream.
    assert dev.get("PointInTimeRecoverySpecification", {}).get(
        "PointInTimeRecoveryEnabled"
    ) in (False, None)
    assert "StreamSpecification" not in dev
    # Prod: PITR on, Stream NEW_AND_OLD_IMAGES.
    assert prod["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert prod["StreamSpecification"]["StreamViewType"] == "NEW_AND_OLD_IMAGES"


def test_data_stack_users_kms_cmk_in_prod_default_in_dev(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(_data_stack("dev", cdk_env), "ContriCool-Users-dev")[
        "Properties"
    ]
    prod = _find_table(_data_stack("prod", cdk_env), "ContriCool-Users-prod")[
        "Properties"
    ]
    # Dev uses AWS-managed key — SSESpecification absent or KMSMasterKeyId
    # empty (CDK emits no SSESpecification for the default AWS-managed
    # path).
    dev_sse = dev.get("SSESpecification", {})
    assert dev_sse.get("KMSMasterKeyId") in (None, "")
    # Prod uses CMK reference (string).
    prod_sse = prod["SSESpecification"]
    assert prod_sse["SSEEnabled"] is True
    assert prod_sse["SSEType"] == "KMS"
    assert prod_sse["KMSMasterKeyId"] is not None


def test_data_stack_users_table_retention_in_prod_destroy_in_dev(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(_data_stack("dev", cdk_env), "ContriCool-Users-dev")
    prod = _find_table(_data_stack("prod", cdk_env), "ContriCool-Users-prod")
    assert dev.get("DeletionPolicy") == "Delete"
    assert prod.get("DeletionPolicy") == "Retain"
    assert prod["Properties"].get("DeletionProtectionEnabled") is True


# ---- Phase 4a — Transactions table ------------------------------------


def test_data_stack_two_tables_synthesise(cdk_env: cdk.Environment) -> None:
    """Phase 4a — DataStack now synthesises two DDB tables (Users +
    Transactions). Both are PAY_PER_REQUEST and share the ``ttl`` TTL
    attribute name."""
    template = _data_stack("dev", cdk_env)
    tables = template.find_resources("AWS::DynamoDB::Table")
    assert len(tables) == 2, (
        f"DataStack must synthesise exactly two tables; got "
        f"{[t['Properties'].get('TableName') for t in tables.values()]}"
    )
    names = {t["Properties"]["TableName"] for t in tables.values()}
    assert names == {"ContriCool-Users-dev", "ContriCool-Transactions-dev"}
    for resource in tables.values():
        props = resource["Properties"]
        assert props["BillingMode"] == "PAY_PER_REQUEST"
        ttl = props["TimeToLiveSpecification"]
        assert ttl["AttributeName"] == "ttl"
        assert ttl["Enabled"] is True


def test_data_stack_transactions_keys_billing_ttl(
    cdk_env: cdk.Environment,
) -> None:
    template = _data_stack("dev", cdk_env)
    props = _find_table(template, "ContriCool-Transactions-dev")["Properties"]
    assert props["BillingMode"] == "PAY_PER_REQUEST"
    keys = {k["AttributeName"]: k["KeyType"] for k in props["KeySchema"]}
    assert keys == {"PK": "HASH", "SK": "RANGE"}
    attrs = {a["AttributeName"]: a["AttributeType"] for a in props["AttributeDefinitions"]}
    assert attrs == {
        "PK": "S",
        "SK": "S",
        "GSI1PK": "S",
        "GSI1SK": "S",
    }
    ttl = props["TimeToLiveSpecification"]
    assert ttl["AttributeName"] == "ttl"
    assert ttl["Enabled"] is True


def test_data_stack_transactions_gsi1_keys_and_projection_all(
    cdk_env: cdk.Environment,
) -> None:
    template = _data_stack("dev", cdk_env)
    props = _find_table(template, "ContriCool-Transactions-dev")["Properties"]
    gsis = props["GlobalSecondaryIndexes"]
    assert len(gsis) == 1
    gsi1 = gsis[0]
    assert gsi1["IndexName"] == "GSI1"
    assert {k["AttributeName"]: k["KeyType"] for k in gsi1["KeySchema"]} == {
        "GSI1PK": "HASH",
        "GSI1SK": "RANGE",
    }
    assert gsi1["Projection"]["ProjectionType"] == "ALL"


def test_data_stack_transactions_pitr_streams_only_in_prod(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(
        _data_stack("dev", cdk_env), "ContriCool-Transactions-dev"
    )["Properties"]
    prod = _find_table(
        _data_stack("prod", cdk_env), "ContriCool-Transactions-prod"
    )["Properties"]
    # Dev: PITR off, no Stream.
    assert dev.get("PointInTimeRecoverySpecification", {}).get(
        "PointInTimeRecoveryEnabled"
    ) in (False, None)
    assert "StreamSpecification" not in dev
    # Prod: PITR on, Stream NEW_AND_OLD_IMAGES.
    assert prod["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert prod["StreamSpecification"]["StreamViewType"] == "NEW_AND_OLD_IMAGES"


def test_data_stack_transactions_kms_cmk_in_prod_default_in_dev(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(
        _data_stack("dev", cdk_env), "ContriCool-Transactions-dev"
    )["Properties"]
    prod = _find_table(
        _data_stack("prod", cdk_env), "ContriCool-Transactions-prod"
    )["Properties"]
    dev_sse = dev.get("SSESpecification", {})
    assert dev_sse.get("KMSMasterKeyId") in (None, "")
    prod_sse = prod["SSESpecification"]
    assert prod_sse["SSEEnabled"] is True
    assert prod_sse["SSEType"] == "KMS"
    assert prod_sse["KMSMasterKeyId"] is not None


def test_data_stack_transactions_retention_in_prod_destroy_in_dev(
    cdk_env: cdk.Environment,
) -> None:
    dev = _find_table(
        _data_stack("dev", cdk_env), "ContriCool-Transactions-dev"
    )
    prod = _find_table(
        _data_stack("prod", cdk_env), "ContriCool-Transactions-prod"
    )
    assert dev.get("DeletionPolicy") == "Delete"
    assert prod.get("DeletionPolicy") == "Retain"
    assert prod["Properties"].get("DeletionProtectionEnabled") is True


def test_data_stack_transactions_table_outputs_present(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 4a — both name + arn outputs in dev, all three (incl. stream
    arn) in prod."""
    dev = _data_stack("dev", cdk_env)
    prod = _data_stack("prod", cdk_env)

    # Avoid relying on logical-id-stable Output keys; assert by description
    # substring (descriptions are stable contracts in design.md).
    def _output_descriptions(template: assertions.Template) -> list[str]:
        outputs = template.find_outputs("*")
        return [o.get("Description", "") for o in outputs.values()]

    dev_descs = _output_descriptions(dev)
    prod_descs = _output_descriptions(prod)

    assert any("Transactions table name" in d for d in dev_descs)
    assert any("Transactions table ARN" in d for d in dev_descs)
    assert not any("Transactions DDB Stream ARN" in d for d in dev_descs)

    assert any("Transactions table name" in d for d in prod_descs)
    assert any("Transactions table ARN" in d for d in prod_descs)
    assert any("Transactions DDB Stream ARN" in d for d in prod_descs)


def test_monitoring_stack_prod_has_dashboard(cdk_env: cdk.Environment) -> None:
    from aws_cdk import aws_kms as kms

    app = cdk.App()
    cmk_scope = cdk.Stack(app, "MonitoringCmkScope", env=cdk_env)
    cmk = kms.Key.from_key_arn(
        cmk_scope,
        "Cmk",
        f"arn:aws:kms:us-west-2:111111111111:key/{'p' * 32}",
    )
    api_kwargs = _api_stack_auth_data_kwargs(app, cdk_env, env_name="prod")
    api = ApiStack(
        app,
        "Contricool-Prod-Api",
        env=cdk_env,
        env_name="prod",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=0.1,
        prod_cmk=cmk,
        **api_kwargs,
    )
    mon = MonitoringStack(
        app,
        "Contricool-Prod-Monitoring",
        env=cdk_env,
        env_name="prod",
        api_lambda_alias=api.lambda_alias,
        api_gateway=api.api_gateway,
        users_table=api_kwargs["users_table"],  # type: ignore[arg-type]
        transactions_table=api_kwargs["transactions_table"],  # type: ignore[arg-type]
        alerts_topic_arn="arn:aws:sns:us-west-2:111111111111:Contricool-Alerts",
        include_dashboard=True,
    )
    template = assertions.Template.from_stack(mon)
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)
    template.resource_count_is("AWS::CloudWatch::CompositeAlarm", 1)


# ---- Phase 2c — Auth feature wiring assertions -----------------------


def _api_stack_template(env_name: str, cdk_env: cdk.Environment) -> assertions.Template:
    app = cdk.App()
    stack = ApiStack(
        app,
        f"Contricool-{env_name.capitalize()}-Api",
        env=cdk_env,
        env_name=env_name,
        snapstart=False,
        log_retention_days=14,
        xray_sampling_rate=1.0,
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name=env_name),
    )
    return assertions.Template.from_stack(stack)


def test_api_stack_phase2c_jwt_authorizer_configured(
    cdk_env: cdk.Environment,
) -> None:
    """JWT authorizer points at the per-env Cognito pool with the
    audience set covering all three app clients."""
    template = _api_stack_template("dev", cdk_env)
    authorizers = template.find_resources("AWS::ApiGatewayV2::Authorizer")
    assert len(authorizers) == 1, f"expected exactly 1 authorizer, got {len(authorizers)}"
    props = next(iter(authorizers.values()))["Properties"]
    assert props["AuthorizerType"] == "JWT"
    jwt_config = props["JwtConfiguration"]
    # The audience list ends up referencing CFN tokens for the three
    # client IDs — assert the list length, not the exact values.
    assert len(jwt_config["Audience"]) == 3
    # Issuer URL contains the cognito-idp host pattern.
    assert "Issuer" in jwt_config


def test_api_stack_phase2c_public_auth_routes_have_no_authorizer(
    cdk_env: cdk.Environment,
) -> None:
    """Routes for the seven auth-bootstrap endpoints + /v1/health must
    NOT carry an authorizer."""
    template = _api_stack_template("dev", cdk_env)
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    public_paths = {
        "POST /v1/auth/signup",
        "POST /v1/auth/verify-email",
        "POST /v1/auth/resend-email-code",
        "POST /v1/auth/login",
        "POST /v1/auth/refresh",
        "POST /v1/auth/forgot-password",
        "POST /v1/auth/reset-password",
        "GET /v1/health",
    }
    found_public: set[str] = set()
    for props in routes.values():
        rk = props["Properties"].get("RouteKey", "")
        if rk in public_paths:
            assert "AuthorizerId" not in props["Properties"], (
                f"public route {rk!r} unexpectedly has an authorizer"
            )
            found_public.add(rk)
    missing = public_paths - found_public
    assert not missing, f"public routes missing from synthesised template: {missing}"


def test_api_stack_phase2c_logout_route_uses_jwt_authorizer(
    cdk_env: cdk.Environment,
) -> None:
    template = _api_stack_template("dev", cdk_env)
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    logout_routes = [
        props
        for props in routes.values()
        if props["Properties"].get("RouteKey") == "POST /v1/auth/logout"
    ]
    assert len(logout_routes) == 1
    props = logout_routes[0]["Properties"]
    assert props.get("AuthorizationType") == "JWT"
    assert props.get("AuthorizerId")


def test_api_stack_phase2c_catchall_route_uses_jwt_authorizer(
    cdk_env: cdk.Environment,
) -> None:
    template = _api_stack_template("dev", cdk_env)
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    catchall = [
        props
        for props in routes.values()
        if props["Properties"].get("RouteKey", "").endswith("/{proxy+}")
    ]
    assert len(catchall) == 1
    props = catchall[0]["Properties"]
    assert props.get("AuthorizationType") == "JWT"


def test_api_stack_phase2c_per_route_throttling_present(
    cdk_env: cdk.Environment,
) -> None:
    """Stage default-route + per-route throttles match design.md.

    The route-settings map is required for /v1/auth/login,
    /v1/auth/resend-email-code, and /v1/auth/forgot-password
    (CLAUDE.md red-line 2)."""
    import json

    template = _api_stack_template("dev", cdk_env)
    stages = template.find_resources("AWS::ApiGatewayV2::Stage")
    blob = json.dumps(list(stages.values()))
    for path in (
        "POST /v1/auth/login",
        "POST /v1/auth/resend-email-code",
        "POST /v1/auth/forgot-password",
    ):
        assert path in blob, f"per-route throttle missing for {path!r}"


def test_api_stack_phase2c_lambda_iam_cognito_actions_enumerated(
    cdk_env: cdk.Environment,
) -> None:
    """Lambda IAM must enumerate cognito-idp actions explicitly. ``*``
    or wildcard ``cognito-idp:*`` is rejected — N31 negative."""
    import json

    template = _api_stack_template("dev", cdk_env)
    policies = template.find_resources("AWS::IAM::Policy")
    blob = json.dumps(list(policies.values()))

    # The eight enumerated actions must all appear.
    for action in (
        "cognito-idp:SignUp",
        "cognito-idp:ConfirmSignUp",
        "cognito-idp:ResendConfirmationCode",
        "cognito-idp:InitiateAuth",
        "cognito-idp:GlobalSignOut",
        "cognito-idp:ForgotPassword",
        "cognito-idp:ConfirmForgotPassword",
        "cognito-idp:AdminGetUser",
    ):
        assert action in blob, f"Lambda IAM missing required action {action!r}"

    # No wildcard cognito-idp action permitted.
    assert '"cognito-idp:*"' not in blob, (
        "Lambda must not have wildcard cognito-idp:* — enumerate actions"
    )


def test_api_stack_lambda_iam_ddb_actions_enumerated(
    cdk_env: cdk.Environment,
) -> None:
    """Lambda IAM grants are the union of (Phase 2c+3a Users actions)
    + (Phase 4b ConditionCheckItem on Users + read/write set on
    Transactions including TransactWriteItems). No wildcards, no Scan,
    no BatchWriteItem ever."""
    import json

    template = _api_stack_template("dev", cdk_env)
    policies = template.find_resources("AWS::IAM::Policy")
    blob = json.dumps(list(policies.values()))

    # Phase 2c required + Phase 3a additions + Phase 4b additions.
    for action in (
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem",
        "dynamodb:DeleteItem",
        # Phase 4b — required on Users (friendship ConditionCheck) and
        # on Transactions (idempotency ConditionCheck).
        "dynamodb:ConditionCheckItem",
        # Phase 4b — required for the cross-table create-transaction
        # write spanning Users + Transactions.
        "dynamodb:TransactWriteItems",
    ):
        assert action in blob, f"Lambda IAM missing required DDB action {action!r}"

    # Forbidden actions — no wildcards, no Scan, no BatchWriteItem.
    for action in (
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem",
        '"dynamodb:*"',  # quoted to avoid matching enumerated actions
    ):
        assert action not in blob, (
            f"Lambda IAM must NOT grant {action!r}"
        )


def test_api_stack_phase4b_transactions_table_grant_distinct(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 4b — the Lambda's inline policy must reference *two*
    distinct DDB table ARNs (Users + Transactions). The ApiStack
    imports the tables from the upstream Data stack, so they appear
    in the policy as cross-stack ARN tokens (parameters or
    ``Fn::ImportValue``). Belt-and-braces against a future refactor
    that points both ``.grant(...)`` calls at the same table.
    """
    import json

    template = _api_stack_template("dev", cdk_env)
    policies = template.find_resources("AWS::IAM::Policy")
    # Find the Lambda's inline policy by the action enumeration.
    lambda_policies = [
        props
        for props in policies.values()
        if "dynamodb:TransactWriteItems"
        in json.dumps(props["Properties"].get("PolicyDocument", {}))
    ]
    assert len(lambda_policies) == 1, (
        f"Expected exactly one Lambda policy with TransactWriteItems; "
        f"got {len(lambda_policies)}"
    )
    document = lambda_policies[0]["Properties"]["PolicyDocument"]
    statements = document["Statement"]

    # Collect every DDB-table-flavoured Resource entry. Two grant
    # blocks (Users + Transactions); each emits a base ARN plus a
    # ``/index/*`` peer, so we expect ≥ 2 distinct refs after dedup.
    # The refs are CFN intrinsics; serialise to a string for set
    # membership.
    ddb_resource_strs: set[str] = set()
    for st in statements:
        actions = st.get("Action") or []
        if isinstance(actions, str):
            actions = [actions]
        if not any(a.startswith("dynamodb:") for a in actions):
            continue
        resources = st.get("Resource") or []
        if isinstance(resources, list):
            for r in resources:
                ddb_resource_strs.add(json.dumps(r, sort_keys=True))
        else:
            ddb_resource_strs.add(json.dumps(resources, sort_keys=True))

    assert len(ddb_resource_strs) >= 2, (
        f"Lambda policy should reference at least 2 distinct DDB "
        f"table ARNs (Users + Transactions); got "
        f"{len(ddb_resource_strs)}: {ddb_resource_strs}"
    )


def test_api_stack_phase4b_transactions_table_env_var_set(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 4b — Lambda has TRANSACTIONS_TABLE_NAME env var."""
    template = _api_stack_template("dev", cdk_env)
    funcs = template.find_resources("AWS::Lambda::Function")
    matching = [
        f
        for f in funcs.values()
        if "contricool-api" in (f["Properties"].get("FunctionName") or "")
    ]
    assert len(matching) == 1, "Expected exactly one contricool-api Lambda"
    env = matching[0]["Properties"].get("Environment", {}).get("Variables", {})
    assert "TRANSACTIONS_TABLE_NAME" in env, (
        f"Lambda env vars missing TRANSACTIONS_TABLE_NAME; have {sorted(env)}"
    )


def test_api_stack_phase3a_friends_add_throttled(
    cdk_env: cdk.Environment,
) -> None:
    """N31: ``POST /v1/friends/add`` is in the synthesised Stage's
    RouteSettings (per-route throttle attached)."""
    template = _api_stack_template("dev", cdk_env)
    stages = template.find_resources("AWS::ApiGatewayV2::Stage")
    assert len(stages) == 1
    (stage_props,) = stages.values()
    route_settings = stage_props["Properties"].get("RouteSettings", {})
    assert "POST /v1/friends/add" in route_settings
    settings = route_settings["POST /v1/friends/add"]
    assert settings.get("ThrottlingRateLimit") == 1
    assert settings.get("ThrottlingBurstLimit") == 5


def test_api_stack_phase2c_no_unprotected_non_public_routes(
    cdk_env: cdk.Environment,
) -> None:
    """N33 negative: every synthesised route is either in the
    ``_PUBLIC_AUTH_PATHS`` set (plus ``/v1/health``) or carries
    ``AuthorizationType=JWT``.

    A future CDK refactor that drops the authorizer override on
    ``/{proxy+}`` or ``/v1/auth/logout`` would silently expose every
    authenticated endpoint to anonymous traffic — this test is the
    backstop.
    """
    template = _api_stack_template("dev", cdk_env)
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    public_route_keys = {
        "POST /v1/auth/signup",
        "POST /v1/auth/verify-email",
        "POST /v1/auth/resend-email-code",
        "POST /v1/auth/login",
        "POST /v1/auth/refresh",
        "POST /v1/auth/forgot-password",
        "POST /v1/auth/reset-password",
        "GET /v1/health",
        # Phase 6 — frontend telemetry sink. Public so a logged-out
        # error-boundary capture still lands. Per-route throttle
        # caps abuse.
        "POST /v1/telemetry/error",
    }
    offenders: list[str] = []
    for props in routes.values():
        rk = props["Properties"].get("RouteKey", "")
        auth_type = props["Properties"].get("AuthorizationType", "NONE")
        authorizer_id = props["Properties"].get("AuthorizerId")
        # A public route is fine. Otherwise the route MUST have
        # AuthorizationType=JWT and an AuthorizerId reference.
        if rk in public_route_keys:
            continue
        if auth_type != "JWT" or not authorizer_id:
            offenders.append(
                f"{rk!r}: AuthorizationType={auth_type!r}, AuthorizerId={authorizer_id!r}"
            )
    assert not offenders, (
        "Found non-public routes without JWT authorizer attached:\n  "
        + "\n  ".join(offenders)
    )


def test_api_stack_phase2c_stage_depends_on_throttled_routes(
    cdk_env: cdk.Environment,
) -> None:
    """Stage must declare an explicit DependsOn on every route named in
    its ``RouteSettings`` map. Without this, CloudFormation can update
    the Stage in parallel with route creation and reject the changeset
    with ``Unable to find Route by key … within the provided
    RouteSettings`` — the bug that broke the Phase 2c first deploy.
    """
    template = _api_stack_template("dev", cdk_env)
    stages = template.find_resources("AWS::ApiGatewayV2::Stage")
    assert len(stages) == 1, "expected exactly one Stage"
    (stage_props,) = stages.values()
    route_settings = stage_props["Properties"].get("RouteSettings", {})
    depends_on = stage_props.get("DependsOn", [])
    if isinstance(depends_on, str):
        depends_on = [depends_on]

    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    # Map RouteKey → logical id so we can resolve _ROUTE_THROTTLES keys
    # to the synthesised route resource.
    route_logical_id_by_key: dict[str, str] = {
        props["Properties"]["RouteKey"]: logical_id
        for logical_id, props in routes.items()
    }

    missing: list[str] = []
    for route_key in route_settings:
        logical_id = route_logical_id_by_key.get(route_key)
        assert logical_id is not None, (
            f"RouteSettings references {route_key!r} but no matching "
            f"AWS::ApiGatewayV2::Route resource was synthesised"
        )
        if logical_id not in depends_on:
            missing.append(route_key)
    assert not missing, (
        "Stage RouteSettings reference routes without a DependsOn entry:\n  "
        + "\n  ".join(missing)
    )


def test_api_stack_phase2e_cors_credentials_with_strict_origins(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 2e — `allow_credentials=True` requires a strict origin
    allowlist (no `*` per CORS spec).  We list the localhost dev
    origins in source and the production CloudFront origin via SSM.
    """
    template = _api_stack_template("dev", cdk_env)
    apis = template.find_resources("AWS::ApiGatewayV2::Api")
    assert len(apis) == 1, "expected exactly one HTTP API"
    (api_props,) = apis.values()
    cors = api_props["Properties"]["CorsConfiguration"]

    assert cors.get("AllowCredentials") is True
    origins = cors["AllowOrigins"]
    assert isinstance(origins, list)
    assert "*" not in origins, "wildcard origin is illegal with credentials=true"

    assert "http://localhost:8081" in origins
    assert "http://localhost:8082" in origins
    assert "http://localhost:19006" in origins

    # Production origin is CDK-resolved via SSM; the rendered template
    # contains an `Fn::Join` that splices in the `Fn::GetAtt`/`Fn::Sub`
    # for the parameter value.  Just assert that *some* entry contains
    # an `Fn::Join` (i.e. is dynamic), so the CFN template will
    # substitute the real domain at deploy time.
    has_dynamic = any(
        isinstance(o, dict) and ("Fn::Join" in o or "Fn::Sub" in o) for o in origins
    )
    assert has_dynamic, (
        "production CloudFront origin should be a dynamic CFN reference, "
        f"got origins: {origins!r}"
    )

    expose = cors.get("ExposeHeaders") or []
    assert "x-request-id" in expose
    assert "retry-after" in expose


def test_web_stack_phase2e_invalidates_root(
    cdk_env: cdk.Environment,
) -> None:
    """Phase 2e — every deploy must invalidate `/*` so the SPA shell
    refreshes immediately.  The hashed asset filenames Expo emits
    make a wildcard invalidation safe (no over-cache risk).
    """
    app = cdk.App()
    api = ApiStack(
        app,
        "Contricool-Dev-Api",
        env=cdk_env,
        env_name="dev",
        snapstart=True,
        log_retention_days=14,
        xray_sampling_rate=1.0,
        **_api_stack_auth_data_kwargs(app, cdk_env, env_name="dev"),
    )
    stack = WebStack(
        app,
        "Contricool-Dev-Web",
        env=cdk_env,
        env_name="dev",
        api_gateway=api.api_gateway,
        bundle_source_path=_WEB_BUNDLE_FIXTURE,
    )
    template = assertions.Template.from_stack(stack)
    customs = template.find_resources("Custom::CDKBucketDeployment")
    assert customs, "expected a CDKBucketDeployment custom resource"
    paths_seen = [
        props["Properties"].get("DistributionPaths") for props in customs.values()
    ]
    assert any(p == ["/*"] for p in paths_seen), (
        "Phase 2e BucketDeployment must invalidate /* on every deploy; "
        f"got DistributionPaths={paths_seen!r}"
    )
