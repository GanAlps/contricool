"""``Contricool-{env}-Web`` stack.

Combines the static-asset S3 bucket with the CloudFront distribution that
fronts both the SPA bucket and the API Gateway. Originally split into
``Web`` (bucket) and ``Edge`` (distribution) per Design 3, but the CDK
auto-generated bucket policy that grants CloudFront read access on the
bucket creates a stack-cycle when the bucket and distribution live in
separate stacks. Combining them here is the standard CDK workaround.

Behaviors (Design 9):

- ``/v1/*`` and ``/api/*`` → API Gateway HTTP API origin (no caching;
  all viewer headers forwarded except Host).
- everything else → S3 with SPA-fallback CloudFront Function on viewer
  request; default object ``index.html``.

The CloudFront default ``cloudfront.net`` domain is the public hostname
at MVP. Custom domain (``contricool.com``) attaches as an alternate
domain name post-Phase-7 with no behavior changes.
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
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as cloudfront_origins,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3_deployment,
)
from constructs import Construct


class WebStack(Stack):
    """SPA bucket + CloudFront distribution for one environment."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        api_gateway: apigwv2.HttpApi,
        bundle_source_path: str = "../client/dist",
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Private S3 bucket for the static web bundle. Phase 1 ships a
        # "coming soon" placeholder from apps/client/static/; Phase 2+
        # replaces with the Expo web export.
        self.bucket = s3.Bucket(
            self,
            "WebBucket",
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN,
            auto_delete_objects=env_name == "dev",
        )

        # CloudFront Function — viewer-request:
        #   * leave /v1/* and /api/* alone (different behavior routes them).
        #   * leave anything with a file extension alone.
        #   * rewrite all other paths to /index.html for SPA deep-linking.
        spa_fallback = cloudfront.Function(
            self,
            "SpaFallbackFunction",
            comment="SPA fallback: rewrite unknown non-asset paths to /index.html",
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            code=cloudfront.FunctionCode.from_inline(_SPA_FALLBACK_JS),
        )

        # Security response headers — applied to all responses.
        response_headers = cloudfront.ResponseHeadersPolicy(
            self,
            "ResponseHeaders",
            response_headers_policy_name=f"contricool-headers-{env_name}",
            comment="ContriCool security response headers",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365),
                    include_subdomains=True,
                    preload=True,
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY,
                    override=True,
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
                xss_protection=cloudfront.ResponseHeadersXSSProtection(
                    protection=True,
                    mode_block=True,
                    override=True,
                ),
                # CSP must go through ``security_headers_behavior``, not
                # ``custom_headers_behavior``: CloudFront rejects
                # ``Content-Security-Policy`` as a custom header with
                # "is a security header and cannot be set as custom header"
                # (the rejected list also includes HSTS, X-Frame-Options,
                # X-Content-Type-Options, Referrer-Policy, X-XSS-Protection).
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=(
                        "default-src 'self'; "
                        "img-src 'self' data:; "
                        "script-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; "
                        "connect-src 'self'; "
                        "frame-ancestors 'none'"
                    ),
                    override=True,
                ),
            ),
            custom_headers_behavior=cloudfront.ResponseCustomHeadersBehavior(
                # Permissions-Policy is NOT on CloudFront's reserved security-
                # header list, so it stays here.
                custom_headers=[
                    cloudfront.ResponseCustomHeader(
                        header="Permissions-Policy",
                        value="camera=(), microphone=(), geolocation=()",
                        override=True,
                    ),
                ],
            ),
        )

        # API origin: HTTP origin pointing at the API Gateway endpoint.
        api_origin = cloudfront_origins.HttpOrigin(
            domain_name=f"{api_gateway.api_id}.execute-api.{Stack.of(self).region}.amazonaws.com",
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
        )

        # S3 origin via Origin Access Control. Combining Web+Edge in this
        # one stack means the auto-generated bucket policy lands in the
        # same stack as the bucket, with no cycle.
        s3_origin = cloudfront_origins.S3BucketOrigin.with_origin_access_control(
            self.bucket,
            origin_access_levels=[cloudfront.AccessLevel.READ],
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"contricool-{env_name}",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            enable_logging=False,
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=response_headers,
                compress=True,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_fallback,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    ),
                ],
            ),
            additional_behaviors={
                "/v1/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=response_headers,
                    compress=True,
                ),
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=response_headers,
                    compress=True,
                ),
            },
        )

        # Phase 2e: serve the real Expo web bundle.  ../client/dist must
        # exist before `cdk synth` runs — the deploy workflow runs
        # `pnpm --filter @contricool/client build:web` first so the asset
        # is present.  Locally, run the same command before `cdk synth`
        # or the synth will error on the missing path.
        #
        # Cache strategy: 5-minute browser cache on every file via the
        # default cache-control here, plus a `/*` invalidation on every
        # deploy so the SPA shell flips immediately.  Hashed asset
        # filenames (Expo's `dist/_expo/static/*`) are content-addressed,
        # so the short max-age on those is harmless.  Phase 6 revisits
        # with split per-prefix deploys once we have real traffic data.
        s3_deployment.BucketDeployment(
            self,
            "WebDeployment",
            sources=[s3_deployment.Source.asset(bundle_source_path)],
            destination_bucket=self.bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
            cache_control=[
                s3_deployment.CacheControl.set_public(),
                s3_deployment.CacheControl.max_age(Duration.minutes(5)),
            ],
        )

        cdk.CfnOutput(
            self,
            "DistributionDomainName",
            value=self.distribution.distribution_domain_name,
            description=(
                "CloudFront default domain — operator-only (CLAUDE.md "
                "red-line 1). Will be written to SSM "
                "/contricool/<env>/cloudfront-domain by the deploy workflow."
            ),
        )


_SPA_FALLBACK_JS = """\
function handler(event) {
    var request = event.request;
    var uri = request.uri;
    if (uri.startsWith('/v1/') || uri.startsWith('/api/')) {
        return request;
    }
    if (uri.match(/\\.[a-zA-Z0-9]+$/)) {
        return request;
    }
    request.uri = '/index.html';
    return request;
}
"""
