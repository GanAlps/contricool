"""``Contricool-{env}-Monitoring`` stack.

CloudWatch alarms + (prod-only) dashboard. Phase 1 wires the minimum
"site is up" alarms — Lambda errors, API Gateway 5xx. The full alarm set
from Design 11 lands in Phase 6 once we have feature traffic to threshold
against.
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
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct


class MonitoringStack(Stack):
    """CloudWatch alarms + (prod-only) dashboard for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        api_lambda_alias: lambda_.IAlias,
        api_gateway: apigwv2.HttpApi,
        alerts_topic_arn: str,
        include_dashboard: bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        alerts_topic = sns.Topic.from_topic_arn(
            self, "AlertsTopic", topic_arn=alerts_topic_arn
        )
        alarm_action = cw_actions.SnsAction(alerts_topic)

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

        # API Gateway HTTP API metrics — using the explicit metric construct
        # because L2 helpers vary across CDK versions for HTTP APIs.
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

        # Prod-only dashboard — Phase 1 minimal version (a few widgets). The
        # full Design-11 dashboard lands in Phase 6.
        if include_dashboard:
            dashboard = cloudwatch.Dashboard(
                self,
                "ProdDashboard",
                dashboard_name="ContriCool-Prod-Health",
                period_override=cloudwatch.PeriodOverride.AUTO,
            )
            dashboard.add_widgets(
                cloudwatch.GraphWidget(
                    title="Lambda invocations / errors",
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
                    ],
                    width=12,
                    height=6,
                ),
                cloudwatch.GraphWidget(
                    title="API Gateway 4xx / 5xx",
                    left=[
                        cloudwatch.Metric(
                            namespace="AWS/ApiGateway",
                            metric_name="4xx",
                            dimensions_map={"ApiId": api_gateway.api_id},
                            statistic="Sum",
                            period=Duration.minutes(5),
                        ),
                        cloudwatch.Metric(
                            namespace="AWS/ApiGateway",
                            metric_name="5xx",
                            dimensions_map={"ApiId": api_gateway.api_id},
                            statistic="Sum",
                            period=Duration.minutes(5),
                        ),
                    ],
                    width=12,
                    height=6,
                ),
            )
