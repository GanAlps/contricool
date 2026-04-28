"""Account-wide ``Contricool-Shared`` stack.

Holds resources that span both ``dev`` and ``prod`` environments:

- ``OpenIdConnectProvider`` for GitHub Actions OIDC federation.
- Three IAM deploy roles (``Contricool-CI-{Dev,Prod}-Deploy`` and
  ``Contricool-CI-PR-ReadOnly``), each scoped tightly via the OIDC
  ``sub`` claim.
- AWS Budgets with $20 / $30 thresholds on tag ``app=contricool``.
- CloudTrail multi-region trail with a dedicated audit S3 bucket.
- SNS alerts topic subscribed to the operator email.
- Project KMS CMK (``alias/contricool-prod``) for production resources.

Per CLAUDE.md red-lines, all values that vary per environment (account ID,
operator email) are passed in via constructor parameters, never hard-coded.
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
    aws_budgets as budgets,
)
from aws_cdk import (
    aws_cloudtrail as cloudtrail,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as sns_subscriptions,
)
from constructs import Construct


class SharedStack(Stack):
    """Account-wide shared infrastructure (one per AWS account)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_repo: str,
        alerts_email: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._github_repo = github_repo
        self._account = Stack.of(self).account
        self._region = Stack.of(self).region

        # 1. KMS CMK for production resources (DDB, CW Logs, SNS).
        self.prod_cmk = kms.Key(
            self,
            "ProdCmk",
            alias="alias/contricool-prod",
            description=(
                "ContriCool production CMK — DDB, CloudWatch Logs, SNS, SSM SecureString"
            ),
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # 2. CloudTrail audit S3 bucket and trail.
        trail_bucket = s3.Bucket(
            self,
            "CloudTrailBucket",
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            enforce_ssl=True,
            versioned=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-logs",
                    enabled=True,
                    expiration=Duration.days(90),
                    noncurrent_version_expiration=Duration.days(7),
                ),
            ],
        )

        cloudtrail.Trail(
            self,
            "AccountTrail",
            trail_name="Contricool-Account-Trail",
            bucket=trail_bucket,
            is_multi_region_trail=True,
            include_global_service_events=True,
            management_events=cloudtrail.ReadWriteType.ALL,
            send_to_cloud_watch_logs=False,
        )

        # 3. SNS alerts topic — alarms across both environments fan into here,
        # subscribed to operator email.
        #
        # Deliberately **not** encrypted with the project CMK at MVP: the
        # alerts payload is operational metadata (alarm name, threshold,
        # metric) — no PII, no secrets. Adding a CMK without granting
        # ``cloudwatch.amazonaws.com`` / ``budgets.amazonaws.com`` /
        # ``sns.amazonaws.com`` on the key policy silently breaks every
        # publish path. AWS-managed encryption (``aws/sns``) is on by default
        # in transit + at rest and is sufficient for this content.
        self.alerts_topic = sns.Topic(
            self,
            "AlertsTopic",
            topic_name="Contricool-Alerts",
            display_name="ContriCool Alerts",
        )
        self.alerts_topic.add_subscription(
            sns_subscriptions.EmailSubscription(alerts_email)
        )

        # 4. AWS Budgets — account-total at $20 (warn) and $30 (critical),
        # filtered by ``app=contricool`` tag so one personal account can host
        # other side-projects without skewing the budget.
        self._add_account_budget(
            budget_amount=30,
            warn_threshold_pct=66.7,  # 66.7% of $30 ≈ $20
            critical_threshold_pct=100.0,
            email=alerts_email,
        )

        # 5. GitHub Actions OIDC provider — single per account.
        oidc_provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOIDC",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        # 6. Deploy roles — scoped to specific GitHub refs / environments.
        self.dev_deploy_role = self._make_deploy_role(
            "Contricool-CI-Dev-Deploy",
            oidc_provider,
            sub_pattern=f"repo:{github_repo}:ref:refs/heads/main",
            stack_name_prefix="Contricool-Dev-",
            description="GitHub Actions deploys to dev (main branch only)",
        )
        # NB: dev role intentionally has **no** CFN write permissions on
        # Contricool-Shared. Shared owns the prod role's trust policy, so a
        # dev-role grant on Shared would be a privilege-escalation path
        # (rewrite prod trust → assume prod, bypassing the Environment
        # approval gate). Shared changes are a documented one-shot manual
        # operation — see specs/runbooks/first-deploy.md.

        self.prod_deploy_role = self._make_deploy_role(
            "Contricool-CI-Prod-Deploy",
            oidc_provider,
            # Prod role is keyed to the GitHub Environment ``prod`` (the gating
            # mechanism we set up in Phase 0); only workflow runs that pass
            # the manual approval get tokens with this sub claim.
            sub_pattern=f"repo:{github_repo}:environment:prod",
            stack_name_prefix="Contricool-Prod-",
            description="GitHub Actions deploys to prod (gated by Environment approval)",
        )

        self.pr_readonly_role = iam.Role(
            self,
            "ContricoolCIPRReadOnly",
            role_name="Contricool-CI-PR-ReadOnly",
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_repo}:pull_request"
                        ),
                    },
                },
            ),
            description="GitHub Actions read-only role for PR cdk-diff comments",
            max_session_duration=Duration.hours(1),
        )
        # Hand-rolled minimum surface needed by `cdk diff`. Deliberately
        # **not** AWS-managed ``ReadOnlyAccess`` — that policy includes
        # ``secretsmanager:GetSecretValue`` and ``ssm:GetParameter`` on
        # SecureString values, which would let any malicious PR exfiltrate
        # the moment Phase 2 introduces real secrets.
        self.pr_readonly_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResource",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:GetTemplateSummary",
                    "cloudformation:ListStacks",
                    "cloudformation:ListStackResources",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ListChangeSets",
                ],
                resources=[
                    f"arn:aws:cloudformation:{self._region}:{self._account}:stack/Contricool-*/*",
                ],
            )
        )
        # CDK assets live in the bootstrap S3 bucket; cdk diff reads them.
        self.pr_readonly_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::cdk-*-assets-{self._account}-{self._region}",
                    f"arn:aws:s3:::cdk-*-assets-{self._account}-{self._region}/*",
                ],
            )
        )
        # ECR image-asset diffs.
        self.pr_readonly_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:DescribeRepositories",
                    "ecr:DescribeImages",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:ListImages",
                ],
                resources=[
                    f"arn:aws:ecr:{self._region}:{self._account}:repository/cdk-*",
                ],
            )
        )
        # Bootstrap-role lookup (cdk diff calls sts:GetCallerIdentity, etc.).
        self.pr_readonly_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:GetCallerIdentity"],
                resources=["*"],
            )
        )

        # 7. CDK outputs — consumed by GitHub Repo Variables (manual one-time
        # `gh variable set` after first Shared deploy).
        cdk.CfnOutput(
            self,
            "DevDeployRoleArn",
            value=self.dev_deploy_role.role_arn,
            description="Set this as GitHub Repo Variable AWS_DEPLOY_ROLE_DEV",
            export_name="Contricool-Dev-Deploy-Role-Arn",
        )
        cdk.CfnOutput(
            self,
            "ProdDeployRoleArn",
            value=self.prod_deploy_role.role_arn,
            description="Set this as GitHub Repo Variable AWS_DEPLOY_ROLE_PROD",
            export_name="Contricool-Prod-Deploy-Role-Arn",
        )
        cdk.CfnOutput(
            self,
            "PRReadOnlyRoleArn",
            value=self.pr_readonly_role.role_arn,
            description="Set this as GitHub Repo Variable AWS_DEPLOY_ROLE_PR_RO",
            export_name="Contricool-PR-ReadOnly-Role-Arn",
        )
        cdk.CfnOutput(
            self,
            "AlertsTopicArn",
            value=self.alerts_topic.topic_arn,
            description="SNS topic alarms publish to (subscribed to operator email)",
            export_name="Contricool-Alerts-Topic-Arn",
        )

    def _make_deploy_role(
        self,
        role_name: str,
        oidc_provider: iam.IOpenIdConnectProvider,
        *,
        sub_pattern: str,
        stack_name_prefix: str,
        description: str,
    ) -> iam.Role:
        """Construct a per-env deploy role with the minimal CDK-deploy-shaped policy."""
        role = iam.Role(
            self,
            role_name,
            role_name=role_name,
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": sub_pattern,
                    },
                },
            ),
            description=description,
            max_session_duration=Duration.hours(1),
        )
        self._allow_cfn_on_stack_pattern(role, f"{stack_name_prefix}*")
        # Allow CDK to assume the bootstrap roles it needs to do its job.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::{self._account}:role/cdk-*-cfn-exec-role-{self._account}-*",
                    f"arn:aws:iam::{self._account}:role/cdk-*-deploy-role-{self._account}-*",
                    f"arn:aws:iam::{self._account}:role/cdk-*-file-publishing-role-{self._account}-*",
                    f"arn:aws:iam::{self._account}:role/cdk-*-image-publishing-role-{self._account}-*",
                    f"arn:aws:iam::{self._account}:role/cdk-*-lookup-role-{self._account}-*",
                ],
            )
        )
        # Allow reading and writing SSM parameters at the contricool prefix.
        # Read: deploy needs to look up things like the operator email and
        # table names. Write: ``.github/workflows/deploy.yml`` writes the
        # rendered CloudFront domain to ``/contricool/<env>/cloudfront-domain``
        # after each successful deploy so smoke tests + future runbooks can
        # read it without re-querying CloudFormation.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                    "ssm:PutParameter",
                ],
                resources=[
                    f"arn:aws:ssm:{self._region}:{self._account}:parameter/contricool/*",
                ],
            )
        )
        return role

    def _allow_cfn_on_stack_pattern(self, role: iam.Role, stack_name_pattern: str) -> None:
        """Grant CloudFormation deploy actions on stacks matching ``stack_name_pattern``."""
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:CreateStack",
                    "cloudformation:UpdateStack",
                    "cloudformation:DeleteStack",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStackResource",
                    "cloudformation:DescribeStackResources",
                    "cloudformation:GetTemplate",
                    "cloudformation:GetTemplateSummary",
                    "cloudformation:ListStacks",
                    "cloudformation:ValidateTemplate",
                    "cloudformation:ExecuteChangeSet",
                    "cloudformation:CreateChangeSet",
                    "cloudformation:DeleteChangeSet",
                    "cloudformation:DescribeChangeSet",
                    "cloudformation:ListChangeSets",
                    "cloudformation:RollbackStack",
                    "cloudformation:ContinueUpdateRollback",
                ],
                resources=[
                    f"arn:aws:cloudformation:{self._region}:{self._account}:stack/{stack_name_pattern}/*",
                ],
            )
        )

    def _add_account_budget(
        self,
        *,
        budget_amount: int,
        warn_threshold_pct: float,
        critical_threshold_pct: float,
        email: str,
    ) -> None:
        budgets.CfnBudget(
            self,
            "AccountBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="Contricool-Account-Total",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=budget_amount,
                    unit="USD",
                ),
                cost_filters={
                    # Tag-filter so unrelated personal-account spend doesn't
                    # trip Contricool budgets.
                    "TagKeyValue": ["user:app$contricool"],
                },
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=warn_threshold_pct,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL",
                            address=email,
                        ),
                    ],
                ),
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=critical_threshold_pct,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL",
                            address=email,
                        ),
                    ],
                ),
            ],
        )
