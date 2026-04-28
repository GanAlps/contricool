# Runbook — first deploy (one-shot post-Phase-1b merge)

## When to run this

After the Phase 1b PR merges to `main`, before the first GitHub Actions deploy can succeed. This is the one-time bootstrap step that creates the OIDC roles GitHub Actions needs.

## Why a manual one-time step

Chicken-and-egg: GitHub Actions needs IAM roles to deploy, but those roles live inside the `Contricool-Shared` stack which itself needs to be deployed. So we deploy `Contricool-Shared` once from your laptop using the IAM Identity Center session you set up in Phase 0. Every subsequent deploy goes through GitHub Actions.

After this runbook, you should never need to deploy from your laptop again unless:
- You're changing the OIDC trust policy or the deploy roles themselves (rare — the Shared stack rarely changes after this).
- You're recovering from a CI compromise and need to rotate roles.

Both cases are documented as one-off events. Otherwise, **prod is reachable only from CI** per CLAUDE.md § Operational Rules.

## Prereqs

- AWS Identity Center session active (`aws --profile contricool-admin sts get-caller-identity` works).
- pnpm + Python 3.12 + AWS CDK installed (see root `README.md`).
- This runbook executed from a laptop that's not the CI environment.

## Steps

```bash
# 1. Pull main and the merged Phase 1b code.
cd ~/workspace/ContriCool
git checkout main
git pull origin main

# 2. Install CDK app dependencies.
cd apps/infra
pip install -e .[dev]

# 3. Set required env vars.
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text --profile contricool-admin)"
export CDK_DEFAULT_REGION=us-west-2
export CONTRICOOL_ALERTS_EMAIL="<your-operator-email>"     # the one that gets budget warnings + P1 alarms
export AWS_PROFILE=contricool-admin

# 4. Sanity-check synth.
cdk synth Contricool-Shared

# Inspect the synthesized template under cdk.out/. The OIDC provider, three
# deploy roles, AWS Budget, CloudTrail, SNS topic, and KMS CMK should all
# appear. No surprises.

# 5. Deploy the Shared stack.
cdk deploy Contricool-Shared --require-approval never --rollback true
# Watch CloudFormation in the AWS console; expect ~3-5 minutes.

# 6. Capture the output ARNs (you'll feed them into GitHub Repo Variables).
aws cloudformation describe-stacks \
    --stack-name Contricool-Shared \
    --query 'Stacks[0].Outputs' \
    --output table \
    --profile contricool-admin

# Expected outputs:
#   DevDeployRoleArn       arn:aws:iam::<account>:role/Contricool-CI-Dev-Deploy
#   ProdDeployRoleArn      arn:aws:iam::<account>:role/Contricool-CI-Prod-Deploy
#   PRReadOnlyRoleArn      arn:aws:iam::<account>:role/Contricool-CI-PR-ReadOnly
#   AlertsTopicArn         arn:aws:sns:us-west-2:<account>:Contricool-Alerts

# 7. Confirm SNS subscription email.
# AWS will have sent a "Confirm subscription" email to your operator inbox.
# Click the confirmation link or you won't receive any alarms.

# 8. Populate GitHub Repo Variables (consumed by .github/workflows/deploy.yml
#    when we add it in the next PR).
gh variable set AWS_DEPLOY_ROLE_DEV   --body "<DevDeployRoleArn from step 6>"   --repo GanAlps/contricool
gh variable set AWS_DEPLOY_ROLE_PROD  --body "<ProdDeployRoleArn from step 6>"  --repo GanAlps/contricool
gh variable set AWS_DEPLOY_ROLE_PR_RO --body "<PRReadOnlyRoleArn from step 6>" --repo GanAlps/contricool
gh variable set AWS_REGION            --body "us-west-2"                       --repo GanAlps/contricool

# 9. Verify variables are set (values won't display, but list will).
gh variable list --repo GanAlps/contricool

# 10. (Optional) deploy the per-env stacks from your laptop now to validate
#     end-to-end. Phase 1d adds the GitHub Actions deploy workflow that takes
#     over from here.
cdk deploy 'Contricool-Dev-*' --require-approval never --rollback true

# 11. Smoke-test:
DEV_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name Contricool-Dev-Edge \
    --query 'Stacks[0].Outputs[?OutputKey==`DistributionDomainName`].OutputValue' \
    --output text \
    --profile contricool-admin)
curl -fsS "https://${DEV_DOMAIN}/v1/health" | tee /tmp/health.json
curl -fsS "https://${DEV_DOMAIN}/" | head -20    # the "coming soon" page from apps/client/static/index.html

# 12. (Recommended) write the dev CloudFront domain to SSM so the next phase's
#     deploy workflow + your future smoke commands can read it without
#     re-running cloudformation describe-stacks every time. The domain itself
#     is moderately sensitive (CLAUDE.md red-line 1) — it lives in SSM, never
#     in source.
aws ssm put-parameter \
    --name /contricool/dev/cloudfront-domain \
    --value "${DEV_DOMAIN}" \
    --type String \
    --overwrite \
    --profile contricool-admin
```

## After this runbook

- `Contricool-Shared` is deployed and the SNS subscription confirmed.
- Three deploy role ARNs are populated as GitHub Repo Variables.
- (Optional) `Contricool-Dev-*` stacks are deployed; the dev CloudFront URL serves the placeholder web page; `/v1/health` returns 200.
- Next PR (Phase 1d) adds `.github/workflows/deploy.yml`, which from then on takes over deploys to dev (auto on merge) and prod (manual approval gate).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `cdk synth` errors with "CONTRICOOL_ALERTS_EMAIL is unset" | env var missing | `export CONTRICOOL_ALERTS_EMAIL=...` in the same shell |
| Deploy fails with "User: arn:aws:sts::...:assumed-role/AWSReservedSSO_..." not authorized | Identity Center session expired | `aws sso login --profile contricool-admin` |
| CloudFormation says "Resource X already exists" | A previous failed deploy left a resource | Check CloudFormation events; usually `cdk deploy --rollback true` recovers; otherwise delete the orphan in the console and retry |
| SNS subscription email never arrives | Email landed in spam, or `CONTRICOOL_ALERTS_EMAIL` was wrong | Re-deploy with the correct address; AWS will resend the confirmation |
| `/v1/health` returns 502 | Lambda image build failed or LWA misconfigured | Check Lambda function logs in CloudWatch under `/aws/lambda/contricool-api-dev` |

## Rollback

If you need to undo the bootstrap entirely (rare, e.g. moving accounts):

```bash
# Order matters — per-env stacks first, then Shared.
cdk destroy 'Contricool-Dev-*' 'Contricool-Prod-*'
cdk destroy 'Contricool-Shared'
# Manually clean up: KMS CMK has 7-day deletion window; CloudTrail bucket
# has RemovalPolicy.RETAIN — delete via the console once you're sure.
```

## Owner

This runbook covers a one-shot operation. Once executed and verified, it's reference material; future Phase-1+ activity should not require re-running anything here.
