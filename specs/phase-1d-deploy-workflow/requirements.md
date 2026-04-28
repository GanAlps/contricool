# Phase 1d — Deploy Workflow — Requirements

## Overview

GitHub Actions deploy + rollback workflows for ContriCool. Replaces "deploy from a laptop" with "deploy from CI" for every environment after the one-time `Contricool-Shared` bootstrap. Aligned with `EXECUTION_PLAN.md` Phase 1d and CLAUDE.md § Operational Rules.

## User-facing requirements

1. **Continuous deploy to dev**
   A developer who merges a PR to `main` sees their change live on dev within ~10 minutes, with no human intervention beyond the merge itself.

2. **Gated deploy to prod**
   After dev deploys cleanly, a designated reviewer (the repo admin at MVP) must explicitly approve before the same change rolls out to prod. Approval is via GitHub's *Environments → prod* gate, not a separate workflow.

3. **Same artifact dev → prod**
   The Lambda container image deployed to prod is **byte-identical** to the one validated on dev. No second build, no second SHA. Rebuild = retest = different artifact = forbidden.

4. **Smoke check after each deploy**
   After dev deploy, `curl https://<dev-cf-domain>/v1/health` must return 200 with the expected JSON shape, or the workflow fails (and the prod gate never appears).
   Same for prod.

5. **Tag every successful prod deploy**
   When a prod deploy + smoke succeed, tag the merged commit on `main` with `release/<YYYY-MM-DD>-<sha7>` and push. Tags become the rollback targets.

6. **Operator can roll back prod in <5 minutes**
   When prod is on a bad version, the operator runs `rollback.yml` (manual `workflow_dispatch`) with a previous tag as input. Within 5 minutes, prod's `live` Lambda alias points at the prior tag's image, no laptop deploy required.

7. **No long-lived AWS credentials**
   Every job that touches AWS does so via GitHub OIDC (`aws-actions/configure-aws-credentials@v4`), assuming the appropriate role from `Contricool-Shared`. No `AWS_ACCESS_KEY_ID`-style secrets in GitHub.

8. **Deploy fails closed**
   If anything goes wrong — image build, ECR push, OIDC assumption, CFN deploy, smoke test — the workflow fails and the next stage does not run. CFN auto-rolls-back the failed stack (already wired in CDK with `--rollback true`).

## Edge cases / constraints

- **Account quota gate**: prod's API Lambda needs 100 reserved concurrency; if the AWS account quota is below `100 + 10`, the prod deploy will fail at CFN. This is intentional — it forces the operator to raise the quota before exposing prod traffic.
- **Concurrent merges**: two merges to `main` must serialize (no parallel deploys to dev). Achieved via GitHub Actions `concurrency:` with `cancel-in-progress: false`.
- **Re-running the prod gate**: if dev passes and prod is rejected, the operator can re-trigger the workflow on the same commit and re-request approval. No commits required to retry.
- **First run after this PR merges**: must work. The runbook `first-deploy.md` already populated the four GitHub variables and one secret needed.
- **Rollback to a tag that doesn't exist**: workflow must fail loudly with a clear message, not silently no-op.
- **The Lambda quota is currently 10**: dev's reserved concurrency is 5 (PR #5), so dev deploys fit. Prod's reserved is 100, so prod deploys will fail until the operator raises the quota — that's correct.
- **CloudFront propagation**: a fresh CloudFront distribution can take 5-10 min to start serving 200s. The smoke step retries up to 10 times with backoff before failing.

## Out of scope (Phase 2+)

- Database migrations (no DB yet).
- Multi-region failover.
- Canary or weighted alias-shift rollouts (we go 0% → 100% via alias swap; canary lands later if traffic justifies).
- Slack notifications on success/failure (rely on GitHub email + SNS Alerts at MVP).
- Automated rollback on smoke failure (operator-triggered for now).

## Summary

Two workflow files + one supporting runbook:

- `.github/workflows/deploy.yml` — multi-stage pipeline triggered on `push: main`.
- `.github/workflows/rollback.yml` — manual workflow_dispatch, takes a tag, retags `live` alias.
- `specs/runbooks/rollback.md` — playbook for using rollback.yml.

The deploy pipeline is the *source of truth* for what's running in prod. After this PR ships, no human runs `cdk deploy` against prod from any machine — only CI does.
