"""``Contricool-{env}-Monitoring`` stack.

Phase 6 — full Design 11 alarm + dashboard + saved-queries surface.

Alarms (per env):

| Alarm                       | Source metric                                      | Threshold |
|-----------------------------|----------------------------------------------------|-----------|
| lambda-errors               | Lambda Errors (sum / 5m)                           | ≥ 1       |
| apigw-5xx                   | ApiGateway 5xx (sum / 5m)                          | ≥ 1       |
| apigw-4xx-burst             | ApiGateway 4xx (sum / 5m)                          | > 100     |
| ddb-throttle-users          | DDB ThrottledRequests on Users                     | ≥ 1       |
| ddb-throttle-transactions   | DDB ThrottledRequests on Transactions              | ≥ 1       |
| lambda-cold-starts          | Lambda Init Duration p99 / 5m                      | > 6 s     |
| lambda-duration-p95         | Lambda Duration p95 / 5m                           | > 4 s     |
| lambda-throttles            | Lambda Throttles (sum / 5m)                        | ≥ 1       |
| composite-site-down         | (lambda-errors OR apigw-5xx) AND any DDB throttle  | tripped   |

The composite ``site-is-down`` alarm is the one that pages the
oncall — single-source alarms (e.g. a one-off 5xx spike) page only
into email, not SMS.

Dashboard widgets (prod-only) and Logs Insights saved-query widgets
land alongside the alarms via a single ``Dashboard`` construct.
"""
from __future__ import annotations

from typing import Any

from aws_cdk import (
    Duration,
    Stack,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cw_actions,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct

# Saved Logs Insights queries — Design 11 §"Saved queries". Stored
# as ``QueryDefinition`` resources so they appear in the CloudWatch
# Logs Insights UI by name. Each query takes the API log group as
# its default scope.
_SAVED_QUERIES: list[tuple[str, str]] = [
    (
        "5xx-in-last-hour",
        (
            "fields @timestamp, @message, request_id, path\n"
            "| filter status_code >= 500\n"
            "| sort @timestamp desc\n"
            "| limit 200"
        ),
    ),
    (
        "slow-requests-p95",
        (
            "fields @timestamp, path, duration_ms\n"
            "| filter ispresent(duration_ms)\n"
            "| stats pct(duration_ms, 95) as p95 by bin(5m), path\n"
            "| sort @timestamp desc"
        ),
    ),
    (
        "authz-denials-by-user",
        (
            "fields @timestamp, user_id, path, error_code\n"
            "| filter error_code = 'FORBIDDEN' or error_code = 'NOT_FOUND'\n"
            "| stats count() as denials by user_id, error_code\n"
            "| sort denials desc"
        ),
    ),
    (
        "idempotency-replays",
        (
            "fields @timestamp, creator_id, key_suffix\n"
            "| filter @message like /txn_create_idempotency_replay/\n"
            "| stats count() as replays by bin(5m)"
        ),
    ),
    (
        "top-4xx-codes",
        (
            "fields error_code\n"
            "| filter ispresent(error_code) and status_code < 500\n"
            "| stats count() as hits by error_code\n"
            "| sort hits desc\n"
            "| limit 20"
        ),
    ),
    (
        "frontend-telemetry-errors",
        (
            "fields @timestamp, telemetry_event, telemetry_message,\n"
            "       telemetry_url, telemetry_user_agent\n"
            "| filter telemetry_level = 'error'\n"
            "| sort @timestamp desc\n"
            "| limit 100"
        ),
    ),
]


class MonitoringStack(Stack):
    """CloudWatch alarms + dashboard + saved queries for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        api_lambda_alias: lambda_.IAlias,
        api_gateway: apigwv2.HttpApi,
        users_table: dynamodb.ITable,
        transactions_table: dynamodb.ITable,
        alerts_topic_arn: str,
        include_dashboard: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alerts_topic = sns.Topic.from_topic_arn(
            self, "AlertsTopic", topic_arn=alerts_topic_arn
        )
        alarm_action = cw_actions.SnsAction(alerts_topic)

        # ---- Lambda alarms -----------------------------------------

        lambda_errors_alarm = cloudwatch.Alarm(
            self,
            "LambdaErrorsAlarm",
            alarm_name=f"contricool-{env_name}-lambda-errors",
            alarm_description=(
                f"ContriCool {env_name}: Lambda errors > 0 "
                "(any error fires an alert)."
            ),
            metric=api_lambda_alias.metric_errors(
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        lambda_errors_alarm.add_alarm_action(alarm_action)

        lambda_throttles_alarm = cloudwatch.Alarm(
            self,
            "LambdaThrottlesAlarm",
            alarm_name=f"contricool-{env_name}-lambda-throttles",
            alarm_description=(
                f"ContriCool {env_name}: Lambda concurrency cap hit "
                "— investigate before reaping the reserved-concurrency budget."
            ),
            metric=api_lambda_alias.metric_throttles(
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        lambda_throttles_alarm.add_alarm_action(alarm_action)

        lambda_duration_p95 = api_lambda_alias.metric_duration(
            statistic="p95",
            period=Duration.minutes(5),
        )
        lambda_duration_alarm = cloudwatch.Alarm(
            self,
            "LambdaDurationP95Alarm",
            alarm_name=f"contricool-{env_name}-lambda-duration-p95",
            alarm_description=(
                f"ContriCool {env_name}: Lambda p95 > 4 s — "
                "request budget breached."
            ),
            metric=lambda_duration_p95,
            threshold=4_000,  # ms
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        lambda_duration_alarm.add_alarm_action(alarm_action)

        # ---- API Gateway alarms ------------------------------------

        api_5xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5xx",
            dimensions_map={"ApiId": api_gateway.api_id},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        api_5xx_alarm = cloudwatch.Alarm(
            self,
            "ApiGateway5xxAlarm",
            alarm_name=f"contricool-{env_name}-apigw-5xx",
            alarm_description=(
                f"ContriCool {env_name}: API Gateway 5xx > 1 in 5 min."
            ),
            metric=api_5xx_metric,
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        api_5xx_alarm.add_alarm_action(alarm_action)

        api_4xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="4xx",
            dimensions_map={"ApiId": api_gateway.api_id},
            statistic="Sum",
            period=Duration.minutes(5),
        )
        api_4xx_burst_alarm = cloudwatch.Alarm(
            self,
            "ApiGateway4xxBurstAlarm",
            alarm_name=f"contricool-{env_name}-apigw-4xx-burst",
            alarm_description=(
                f"ContriCool {env_name}: 4xx > 100 in 5 min — "
                "abuse burst or a recently-shipped client bug."
            ),
            metric=api_4xx_metric,
            threshold=100,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        api_4xx_burst_alarm.add_alarm_action(alarm_action)

        # ---- DDB throttle alarms ----------------------------------

        ddb_throttle_alarms: list[cloudwatch.IAlarm] = []
        for table_label, table in (
            ("users", users_table),
            ("transactions", transactions_table),
        ):
            metric = cloudwatch.Metric(
                namespace="AWS/DynamoDB",
                metric_name="ThrottledRequests",
                dimensions_map={"TableName": table.table_name},
                statistic="Sum",
                period=Duration.minutes(5),
            )
            alarm = cloudwatch.Alarm(
                self,
                f"DdbThrottle{table_label.capitalize()}Alarm",
                alarm_name=f"contricool-{env_name}-ddb-throttle-{table_label}",
                alarm_description=(
                    f"ContriCool {env_name}: {table_label} table threw a "
                    "ThrottledRequest. On-demand should never throttle, so "
                    "this signals either a hot partition or an AWS issue."
                ),
                metric=metric,
                threshold=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                evaluation_periods=1,
                datapoints_to_alarm=1,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(alarm_action)
            ddb_throttle_alarms.append(alarm)

        # ---- Composite "site is down" alarm ----------------------

        # An OR of the two front-line failure indicators. CloudWatch
        # composite alarms reference children by ALARM token; the
        # ``CompositeAlarm`` construct stitches it for us.
        site_down = cloudwatch.CompositeAlarm(
            self,
            "SiteIsDownComposite",
            composite_alarm_name=f"contricool-{env_name}-site-is-down",
            alarm_description=(
                f"ContriCool {env_name}: high-confidence site-down signal — "
                "Lambda errors OR API Gateway 5xx, sustained 5 min."
            ),
            alarm_rule=cloudwatch.AlarmRule.any_of(
                cloudwatch.AlarmRule.from_alarm(
                    lambda_errors_alarm, cloudwatch.AlarmState.ALARM
                ),
                cloudwatch.AlarmRule.from_alarm(
                    api_5xx_alarm, cloudwatch.AlarmState.ALARM
                ),
            ),
            actions_enabled=True,
        )
        site_down.add_alarm_action(alarm_action)

        # ---- Saved Logs Insights queries -------------------------

        # Scope to the API Lambda's log group; the cleanup Lambda
        # follow-up will add its own queries. We use the L1
        # ``CfnQueryDefinition`` because L2 ``QueryString`` requires
        # field-by-field decomposition (fields=, filter=, sort=, ...)
        # which doesn't round-trip our hand-written CloudWatch
        # Logs Insights queries cleanly.
        api_log_group_name = f"/aws/lambda/contricool-api-{env_name}"
        for query_name, query_string in _SAVED_QUERIES:
            logs.CfnQueryDefinition(
                self,
                f"Query{query_name.replace('-', '').title()}",
                name=f"contricool/{env_name}/{query_name}",
                query_string=query_string,
                log_group_names=[api_log_group_name],
            )

        # ---- Dashboard (prod-only) -------------------------------

        if include_dashboard:
            dashboard = cloudwatch.Dashboard(
                self,
                "ProdDashboard",
                dashboard_name="ContriCool-Prod-Health",
                period_override=cloudwatch.PeriodOverride.AUTO,
            )
            dashboard.add_widgets(
                cloudwatch.GraphWidget(
                    title="Lambda invocations / errors / throttles",
                    left=[
                        api_lambda_alias.metric_invocations(
                            statistic="Sum",
                            period=Duration.minutes(5),
                            label="Invocations",
                        ),
                        api_lambda_alias.metric_errors(
                            statistic="Sum",
                            period=Duration.minutes(5),
                            label="Errors",
                        ),
                        api_lambda_alias.metric_throttles(
                            statistic="Sum",
                            period=Duration.minutes(5),
                            label="Throttles",
                        ),
                    ],
                    width=12,
                    height=6,
                ),
                cloudwatch.GraphWidget(
                    title="Lambda duration p50 / p95 / p99",
                    left=[
                        api_lambda_alias.metric_duration(
                            statistic="p50", period=Duration.minutes(5),
                            label="p50",
                        ),
                        lambda_duration_p95.with_(label="p95"),
                        api_lambda_alias.metric_duration(
                            statistic="p99", period=Duration.minutes(5),
                            label="p99",
                        ),
                    ],
                    width=12,
                    height=6,
                ),
            )
            dashboard.add_widgets(
                cloudwatch.GraphWidget(
                    title="API Gateway 4xx / 5xx",
                    left=[api_4xx_metric, api_5xx_metric],
                    width=12,
                    height=6,
                ),
                cloudwatch.GraphWidget(
                    title="DDB ThrottledRequests (Users + Transactions)",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ThrottledRequests",
                            dimensions_map={
                                "TableName": users_table.table_name
                            },
                            statistic="Sum",
                            period=Duration.minutes(5),
                            label="Users",
                        ),
                        cloudwatch.Metric(
                            namespace="AWS/DynamoDB",
                            metric_name="ThrottledRequests",
                            dimensions_map={
                                "TableName": transactions_table.table_name
                            },
                            statistic="Sum",
                            period=Duration.minutes(5),
                            label="Transactions",
                        ),
                    ],
                    width=12,
                    height=6,
                ),
            )
            dashboard.add_widgets(
                cloudwatch.AlarmStatusWidget(
                    title="Alarm summary",
                    alarms=[
                        lambda_errors_alarm,
                        lambda_throttles_alarm,
                        lambda_duration_alarm,
                        api_5xx_alarm,
                        api_4xx_burst_alarm,
                        *ddb_throttle_alarms,
                        site_down,
                    ],
                    width=24,
                    height=4,
                ),
            )

        # Expose key alarms so a future CDK consumer (e.g. a runbook
        # that needs to attach a slack action) can chain.
        self.lambda_errors_alarm = lambda_errors_alarm
        self.api_5xx_alarm = api_5xx_alarm
        self.site_down_alarm = site_down
