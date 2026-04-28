# apps/infra — AWS CDK infrastructure

CDK app in Python that defines all ContriCool AWS resources.

## Stacks

| Stack | Scope | What it holds |
|---|---|---|
| `Contricool-Shared` | account-wide | GitHub OIDC provider; `Contricool-CI-Dev-Deploy` / `Contricool-CI-Prod-Deploy` / `Contricool-CI-PR-ReadOnly` IAM roles; AWS Budgets ($20/$30 on `app=contricool` tag); CloudTrail multi-region trail + S3 audit bucket; SNS alerts topic; project KMS CMK |
| `Contricool-{Dev,Prod}-Api` | per env | Lambda DockerImageFunction (arm64, SnapStart-on-published-versions, reserved concurrency 100); API Gateway HTTP API with catch-all `/{proxy+}` routing to Lambda; permissive CORS (strict origin allowlist enforced at CloudFront) |
| `Contricool-{Dev,Prod}-Web` | per env | Private S3 bucket + CloudFront distribution with two origins (`/v1/*`, `/api/*` → API Gateway; default → S3 with SPA-fallback CloudFront Function); security response headers policy. Originally split into separate `Web` and `Edge` stacks per Design 3, but combined here to avoid the CDK auto-bucket-policy stack-cycle that arises when CloudFront's OAC bucket policy lives in a different stack from the bucket. |
| `Contricool-{Dev,Prod}-Monitoring` | per env | CloudWatch alarms (Lambda errors, API Gateway 5xx) + (prod-only) dashboard |

`Data` and `Auth` stacks are **not yet present** — they're created in Phase 2 alongside the DDB tables and Cognito user pool.

## Aspects

`SecurityAspect` enforces CLAUDE.md red-line 2 guardrails at synth time:
- Every S3 bucket must have `BlockPublicAccess.BLOCK_ALL`.
- Every Lambda function must have `ReservedConcurrentExecutions` set.
- IAM policies must not use bare `"*"` in `Action`.

Synth fails if any of these are violated. Tests in `tests/test_aspects.py` cover both the failing and passing cases.

## Required env vars

```bash
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text --profile contricool-admin)"
export CDK_DEFAULT_REGION=us-west-2
export CONTRICOOL_ALERTS_EMAIL="your-email@example.com"   # operator inbox for budget + alarm notifications
# CONTRICOOL_GITHUB_REPO defaults to "GanAlps/contricool"
```

`CONTRICOOL_ALERTS_EMAIL` is required — synth fails fast if unset (see `app.py`).

## Local commands

```bash
cd apps/infra
pip install -e .[dev]                # install CDK + test deps
pytest                               # run aspect + synth tests
cdk synth                            # synthesize all stacks → cdk.out/
cdk diff Contricool-Shared           # diff against the deployed Shared stack
cdk deploy Contricool-Shared         # one-time bootstrap; see runbook below
```

## First-time bootstrap (one-shot, run from your laptop after merging Phase 1b)

After merging this PR you need to deploy the `Contricool-Shared` stack **once from your laptop** to create the OIDC roles. After that, all deploys go through GitHub Actions.

Walkthrough lives in `specs/runbooks/first-deploy.md`.

## Code organization

```
apps/infra/
  app.py                    # entry point — instantiates stacks, applies aspects + tags
  cdk.json                  # CDK config
  pyproject.toml
  stacks/
    __init__.py
    shared_stack.py         # account-wide
    api_stack.py            # per-env: Lambda + API Gateway
    web_stack.py            # per-env: SPA S3 bucket + CloudFront distribution
    monitoring_stack.py     # per-env: alarms + dashboard
  aspects/
    __init__.py
    security_aspect.py      # synth-time red-line enforcement
  tests/
    test_aspects.py         # aspect happy + failure paths
    test_synth.py           # smoke synth per stack
  README.md                 # this file
```
