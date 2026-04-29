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
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
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
    )
    stack = WebStack(
        app,
        "Contricool-Dev-Web",
        env=cdk_env,
        env_name="dev",
        api_gateway=api.api_gateway,
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


def test_auth_stack_three_clients_no_secret_with_srp_only(
    cdk_env: cdk.Environment,
) -> None:
    """Three app clients (web/ios/android), all public (no secret), with
    USER_SRP_AUTH + REFRESH_TOKEN_AUTH only."""
    template = _auth_stack("dev", cdk_env)
    clients = template.find_resources("AWS::Cognito::UserPoolClient")
    assert len(clients) == 3
    names = {c["Properties"]["ClientName"] for c in clients.values()}
    assert names == {"web", "ios", "android"}
    for c in clients.values():
        props = c["Properties"]
        assert props.get("GenerateSecret") in (False, None)
        flows = set(props.get("ExplicitAuthFlows", []))
        # CDK expands user_srp=True into ALLOW_USER_SRP_AUTH +
        # ALLOW_REFRESH_TOKEN_AUTH plus CDK's framework helpers
        # (ALLOW_REFRESH_TOKEN_AUTH always); we assert the SRP flow is on
        # and the password-grant flows are off.
        assert "ALLOW_USER_SRP_AUTH" in flows
        assert "ALLOW_REFRESH_TOKEN_AUTH" in flows
        # Password-grant + admin flows MUST NOT be enabled — they bypass SRP.
        forbidden = {
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_ADMIN_USER_PASSWORD_AUTH",
        }
        assert not (flows & forbidden), (
            f"Client {props['ClientName']} has forbidden flows: {flows & forbidden!r}"
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


def test_data_stack_table_keys_billing_ttl(cdk_env: cdk.Environment) -> None:
    template = _data_stack("dev", cdk_env)
    tables = template.find_resources("AWS::DynamoDB::Table")
    assert len(tables) == 1
    props = next(iter(tables.values()))["Properties"]
    assert props["TableName"] == "ContriCool-Users-dev"
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


def test_data_stack_gsi1_keys_and_projection_all(cdk_env: cdk.Environment) -> None:
    template = _data_stack("dev", cdk_env)
    props = next(iter(template.find_resources("AWS::DynamoDB::Table").values()))[
        "Properties"
    ]
    gsis = props["GlobalSecondaryIndexes"]
    assert len(gsis) == 1
    gsi1 = gsis[0]
    assert gsi1["IndexName"] == "GSI1"
    assert {k["AttributeName"]: k["KeyType"] for k in gsi1["KeySchema"]} == {
        "GSI1PK": "HASH",
        "GSI1SK": "RANGE",
    }
    assert gsi1["Projection"]["ProjectionType"] == "ALL"


def test_data_stack_pitr_streams_only_in_prod(cdk_env: cdk.Environment) -> None:
    dev = next(iter(_data_stack("dev", cdk_env).find_resources("AWS::DynamoDB::Table").values()))[
        "Properties"
    ]
    prod = next(iter(_data_stack("prod", cdk_env).find_resources("AWS::DynamoDB::Table").values()))[
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


def test_data_stack_kms_cmk_in_prod_default_in_dev(cdk_env: cdk.Environment) -> None:
    dev = next(iter(_data_stack("dev", cdk_env).find_resources("AWS::DynamoDB::Table").values()))[
        "Properties"
    ]
    prod = next(iter(_data_stack("prod", cdk_env).find_resources("AWS::DynamoDB::Table").values()))[
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
    dev = next(iter(_data_stack("dev", cdk_env).find_resources("AWS::DynamoDB::Table").values()))
    prod = next(iter(_data_stack("prod", cdk_env).find_resources("AWS::DynamoDB::Table").values()))
    assert dev.get("DeletionPolicy") == "Delete"
    assert prod.get("DeletionPolicy") == "Retain"
    assert prod["Properties"].get("DeletionProtectionEnabled") is True


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
