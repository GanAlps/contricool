"""``Contricool-{env}-Auth`` stack.

Creates the per-environment Cognito User Pool, three per-platform App
Clients, and the ``/contricool/<env>/pii-salt`` SSM SecureString. No
identity is created here — this is pure plumbing.

Schema is the contract specified in ``specs/04-authentication/design.md``:

- Email is the required + verified sign-in attribute.
- Phone is optional + unverified (no SMS configuration on the pool).
- ``custom:user_id`` is the only custom attribute (ULID, len 26, immutable).
- Cognito-managed email sender at MVP (no SES domain yet).
- MFA off; password policy 10/upper/lower/digit/symbol; password history 3.

Phase 2c will add Cognito user-pool triggers (PreSignUp, PostConfirmation)
and wire the pool into the API Gateway HTTP API as a JWT authorizer; this
stack only stands up the pool.
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
    aws_cognito as cognito,
)
from constructs import Construct

from cdk_constructs.pii_salt import PiiSalt

_PASSWORD_HISTORY_DEPTH = 3


class AuthStack(Stack):
    """Cognito User Pool + 3 App Clients + PII salt for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        prod_cmk_arn: str | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._env_name = env_name
        is_prod = env_name == "prod"

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"contricool-{env_name}",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
                phone_number=cognito.StandardAttribute(
                    required=False, mutable=True
                ),
                fullname=cognito.StandardAttribute(required=True, mutable=True),
            ),
            custom_attributes={
                "user_id": cognito.StringAttribute(
                    min_len=26, max_len=26, mutable=False
                ),
            },
            password_policy=cognito.PasswordPolicy(
                min_length=10,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(1),
            ),
            mfa=cognito.Mfa.OFF,
            email=cognito.UserPoolEmail.with_cognito(
                "ContriCool <no-reply@verificationemail.com>"
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            deletion_protection=is_prod,
        )

        # Cognito L2 doesn't expose password history. Set it via CFN override.
        cfn_pool = self.user_pool.node.default_child
        assert isinstance(cfn_pool, cdk.CfnResource)
        cfn_pool.add_property_override(
            "Policies.PasswordPolicy.PasswordHistorySize",
            _PASSWORD_HISTORY_DEPTH,
        )

        # Each App Client is identical in policy — only the platform name
        # differs. Helper keeps the contract typed without a ``**kwargs``
        # blob (``dict[str, object]`` defeats mypy at the call site).
        def make_client(construct_id: str, name: str) -> cognito.UserPoolClient:
            return cognito.UserPoolClient(
                self,
                construct_id,
                user_pool=self.user_pool,
                user_pool_client_name=name,
                auth_flows=cognito.AuthFlow(user_srp=True),
                prevent_user_existence_errors=True,
                enable_token_revocation=True,
                generate_secret=False,
                access_token_validity=Duration.hours(1),
                id_token_validity=Duration.hours(1),
                refresh_token_validity=Duration.days(30),
                # No OAuth flows — federation deferred. Disabling explicitly
                # so we don't accidentally pick up CDK defaults.
                o_auth=cognito.OAuthSettings(
                    flows=cognito.OAuthFlows(
                        authorization_code_grant=False,
                        implicit_code_grant=False,
                        client_credentials=False,
                    ),
                    scopes=[],
                    callback_urls=[],
                    logout_urls=[],
                ),
                supported_identity_providers=[
                    cognito.UserPoolClientIdentityProvider.COGNITO,
                ],
            )

        self.web_client = make_client("WebClient", "web")
        self.ios_client = make_client("IosClient", "ios")
        self.android_client = make_client("AndroidClient", "android")

        self.pii_salt = PiiSalt(
            self,
            "PiiSalt",
            env_name=env_name,
            kms_key_arn=prod_cmk_arn if is_prod else None,
        )

        cdk.CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description=(
                "Cognito User Pool ID — written to "
                f"/contricool/{env_name}/cognito/user-pool-id by deploy.yml."
            ),
        )
        cdk.CfnOutput(
            self,
            "UserPoolArn",
            value=self.user_pool.user_pool_arn,
            description="Cognito User Pool ARN (consumed by API Gateway authorizer).",
        )
        cdk.CfnOutput(
            self,
            "WebClientId",
            value=self.web_client.user_pool_client_id,
            description=f"web App Client ID → /contricool/{env_name}/cognito/client-id-web",
        )
        cdk.CfnOutput(
            self,
            "IosClientId",
            value=self.ios_client.user_pool_client_id,
            description=f"ios App Client ID → /contricool/{env_name}/cognito/client-id-ios",
        )
        cdk.CfnOutput(
            self,
            "AndroidClientId",
            value=self.android_client.user_pool_client_id,
            description=(
                "android App Client ID → "
                f"/contricool/{env_name}/cognito/client-id-android"
            ),
        )
