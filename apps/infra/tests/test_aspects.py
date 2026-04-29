"""Tests for the SecurityAspect.

Each test synthesizes a tiny stack containing one offending resource and
asserts that synth surfaces an error matching the expected guardrail. Tests
also cover the happy path (no error when the resource is correctly
configured).
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk import (
    Stack,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_s3 as s3,
)

from aspects.security_aspect import SecurityAspect


@pytest.fixture
def cdk_outdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    out = tmp_path / "cdk.out"
    monkeypatch.setenv("CDK_OUTDIR", str(out))
    yield out


def _collect_errors(app: cdk.App) -> list[str]:
    """Synth and return all error annotations across the app, never raising."""
    # cdk.App.synth() raises if there are validation errors. Catch and surface.
    try:
        app.synth(force=True)
    except Exception:
        pass  # errors will be visible via annotations below
    errors: list[str] = []
    for child in app.node.find_all():
        # Each construct has an annotations registry on its metadata; CDK
        # exposes them via cdk.Annotations.
        for entry in child.node.metadata:
            if entry.type == "aws:cdk:error":
                errors.append(str(entry.data))
    return errors


def test_bucket_without_block_public_access_emits_error(cdk_outdir: Path) -> None:
    app = cdk.App(outdir=str(cdk_outdir))
    stack = Stack(app, "TestStack")
    s3.Bucket(stack, "OffendingBucket")  # no block_public_access set
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    assert any("BlockPublicAccess.BLOCK_ALL" in e for e in errors), (
        f"Expected BlockPublicAccess error; got: {errors!r}"
    )


def test_bucket_with_block_public_access_emits_no_error(cdk_outdir: Path) -> None:
    app = cdk.App(outdir=str(cdk_outdir))
    stack = Stack(app, "TestStack")
    s3.Bucket(
        stack,
        "GoodBucket",
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
    )
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    bucket_errors = [e for e in errors if "BlockPublicAccess" in e]
    assert not bucket_errors, (
        f"Expected no bucket errors for properly-configured bucket; got: {bucket_errors!r}"
    )


def test_lambda_without_reserved_concurrency_emits_error(cdk_outdir: Path) -> None:
    app = cdk.App(outdir=str(cdk_outdir))
    stack = Stack(app, "TestStack")
    lambda_.Function(
        stack,
        "OffendingLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context):\n    return {}\n"),
    )
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    assert any("ReservedConcurrentExecutions" in e for e in errors), (
        f"Expected ReservedConcurrentExecutions error; got: {errors!r}"
    )


def test_lambda_with_reserved_concurrency_emits_no_error(cdk_outdir: Path) -> None:
    app = cdk.App(outdir=str(cdk_outdir))
    stack = Stack(app, "TestStack")
    lambda_.Function(
        stack,
        "GoodLambda",
        runtime=lambda_.Runtime.PYTHON_3_12,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context):\n    return {}\n"),
        reserved_concurrent_executions=10,
    )
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    lambda_errors = [e for e in errors if "ReservedConcurrentExecutions" in e]
    assert not lambda_errors, (
        f"Expected no lambda errors for properly-configured function; got: {lambda_errors!r}"
    )


def test_cdk_internal_lambdas_are_exempt_from_concurrency_check(cdk_outdir: Path) -> None:
    """CDK-managed provider Lambdas (BucketDeployment, auto_delete_objects)
    cannot have reserved concurrency configured by the user. The Aspect must
    skip them so synth still succeeds."""
    from aws_cdk import (
        aws_s3 as s3,
    )
    from aws_cdk import (
        aws_s3_deployment as s3_deployment,
    )

    app = cdk.App(outdir=str(cdk_outdir))
    stack = Stack(app, "TestStack")
    bucket = s3.Bucket(
        stack,
        "ExemptBucket",
        block_public_access=s3.BlockPublicAccess(
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
        ),
        encryption=s3.BucketEncryption.S3_MANAGED,
        removal_policy=cdk.RemovalPolicy.DESTROY,
        auto_delete_objects=True,
    )
    s3_deployment.BucketDeployment(
        stack,
        "ExemptDeployment",
        sources=[s3_deployment.Source.data("hello.txt", "hi")],
        destination_bucket=bucket,
    )
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    concurrency_errors = [e for e in errors if "ReservedConcurrentExecutions" in e]
    assert not concurrency_errors, (
        "BucketDeployment + auto_delete_objects provider lambdas must be "
        f"exempt from the concurrency check; got: {concurrency_errors!r}"
    )


def test_pii_salt_provider_lambda_passes_aspect(cdk_outdir: Path) -> None:
    """The PII-salt construct creates two Lambdas:

    1. The user-defined ``ProviderFn`` — we set ``reserved_concurrent_executions=1``
       on it, so the Aspect rule is satisfied directly.
    2. The CDK ``Provider`` framework Lambda (``framework-onEvent``) — already
       on the SecurityAspect exemption list.

    Both must pass without emitting ``ReservedConcurrentExecutions`` errors."""
    from stacks.auth_stack import AuthStack

    app = cdk.App(outdir=str(cdk_outdir))
    AuthStack(
        app,
        "Contricool-Dev-Auth",
        env=cdk.Environment(account="111111111111", region="us-west-2"),
        env_name="dev",
        prod_cmk_arn=None,
    )
    cdk.Aspects.of(app).add(SecurityAspect())

    errors = _collect_errors(app)
    concurrency_errors = [e for e in errors if "ReservedConcurrentExecutions" in e]
    assert not concurrency_errors, (
        "PII-salt provider Lambda must pass the concurrency Aspect "
        f"(provider sets reserved=1, framework path is exempted); got: {concurrency_errors!r}"
    )
