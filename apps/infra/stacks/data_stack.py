"""``Contricool-{env}-Data`` stack.

Creates the per-environment DynamoDB tables described in
``specs/07-database-data-model/design.md``:

- ``ContriCool-Users-<env>`` — social-graph + identity table (Phase 2a).
  Composite PK + SK; one GSI (``GSI1``) — polymorphic across
  ``EMAIL#<hash>`` lookup hits and ``USER#<max>`` reverse-friendship rows.
- ``ContriCool-Transactions-<env>`` — financial-ledger table (Phase 4a).
  Composite PK + SK; one GSI (``GSI1``) keyed by ``USER#<user_id>`` for
  Pattern #8 ("list my transactions, by date desc").

Both tables share the same per-environment encryption choice (AWS-managed in
dev, customer-managed CMK in prod), the same ``ttl`` attribute name (used by
``RATE#`` and ``IDEMPOTENCY#`` rows), on-demand billing, and prod-only PITR
+ DDB Streams + retain-on-destroy.
"""
from __future__ import annotations

from typing import Any

import aws_cdk as cdk
from aws_cdk import (
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_kms as kms,
)
from constructs import Construct


class DataStack(Stack):
    """The two DynamoDB tables for one environment.

    Public attributes (consumed by ``ApiStack`` via ``app.py``):

    - ``users_table`` — Phase 2a.
    - ``transactions_table`` — Phase 4a (Phase 4b wires it into the API
      Lambda's IAM grants and env vars).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        prod_cmk: kms.IKey | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._env_name = env_name
        is_prod = env_name == "prod"

        encryption_kwargs: dict[str, Any]
        if is_prod:
            assert prod_cmk is not None, "prod DataStack requires the project CMK"
            encryption_kwargs = {
                "encryption": dynamodb.TableEncryption.CUSTOMER_MANAGED,
                "encryption_key": prod_cmk,
            }
        else:
            # AWS-managed key — free, no key policy to maintain.
            encryption_kwargs = {
                "encryption": dynamodb.TableEncryption.AWS_MANAGED,
            }

        self.users_table = dynamodb.Table(
            self,
            "UsersTable",
            table_name=f"ContriCool-Users-{env_name}",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=is_prod,
            ),
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES if is_prod else None,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            deletion_protection=is_prod,
            **encryption_kwargs,
        )

        self.users_table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        self.transactions_table = dynamodb.Table(
            self,
            "TransactionsTable",
            table_name=f"ContriCool-Transactions-{env_name}",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=is_prod,
            ),
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES if is_prod else None,
            removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            deletion_protection=is_prod,
            **encryption_kwargs,
        )

        self.transactions_table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        cdk.CfnOutput(
            self,
            "UsersTableName",
            value=self.users_table.table_name,
            description=(
                f"Users table name → /contricool/{env_name}/ddb/users-table-name"
            ),
        )
        cdk.CfnOutput(
            self,
            "UsersTableArn",
            value=self.users_table.table_arn,
            description="Users table ARN (consumed by API Lambda IAM policy).",
        )
        if is_prod:
            # Streams are explicitly enabled for prod above; missing ARN here
            # would mean CDK silently dropped the StreamSpecification —
            # surface that as a synth failure rather than emitting an empty
            # CfnOutput.
            stream_arn = self.users_table.table_stream_arn
            assert stream_arn is not None, (
                "Prod Users table has Streams enabled but table_stream_arn "
                "is None — CDK lost the StreamSpecification."
            )
            cdk.CfnOutput(
                self,
                "UsersTableStreamArn",
                value=stream_arn,
                description="Users DDB Stream ARN — no consumer at MVP.",
            )

        cdk.CfnOutput(
            self,
            "TransactionsTableName",
            value=self.transactions_table.table_name,
            description=(
                f"Transactions table name → "
                f"/contricool/{env_name}/ddb/transactions-table-name"
            ),
        )
        cdk.CfnOutput(
            self,
            "TransactionsTableArn",
            value=self.transactions_table.table_arn,
            description="Transactions table ARN (consumed by API Lambda IAM policy).",
        )
        if is_prod:
            txn_stream_arn = self.transactions_table.table_stream_arn
            assert txn_stream_arn is not None, (
                "Prod Transactions table has Streams enabled but "
                "table_stream_arn is None — CDK lost the StreamSpecification."
            )
            cdk.CfnOutput(
                self,
                "TransactionsTableStreamArn",
                value=txn_stream_arn,
                description="Transactions DDB Stream ARN — no consumer at MVP.",
            )
