# Phase 1d — Deploy Workflow — Tasks

Phased to keep each commit shippable in isolation. Tests for each phase ship in the same phase.

## Phase A — Author `deploy.yml`

- [ ] **A1.** Create `.github/workflows/deploy.yml` with `on: push: [main]` trigger and concurrency group.
- [ ] **A2.** Add `deploy-dev` job:
  - Checkout, setup-python 3.12, setup-node 22, npm install -g aws-cdk
  - `pip install -e 'apps/infra[dev]'`
  - Configure AWS via OIDC using `vars.AWS_DEPLOY_ROLE_DEV`
  - `environment: dev`
  - Run `cdk deploy 'Contricool-Dev-*' --require-approval never --rollback true` from `apps/infra/` with `CDK_DEFAULT_ACCOUNT`/`CDK_DEFAULT_REGION`/`CONTRICOOL_ALERTS_EMAIL` env vars set
  - Output the dev CloudFront domain via `aws cloudformation describe-stacks` and `$GITHUB_OUTPUT`
  - Output the dev Lambda `CodeSha256` via `aws lambda get-function`
- [ ] **A3.** Add `smoke-dev` job:
  - `needs: deploy-dev`
  - `environment: dev`
  - Read domain from previous job's output
  - Curl `/v1/health` with 10x retry / 10s backoff; assert `status==ok` and `env==dev` via `jq`
- [ ] **A4.** Add `deploy-prod` job:
  - `needs: smoke-dev`
  - `environment: prod` (gates on the existing required-reviewer rule from Phase 0)
  - Configure AWS via OIDC using `vars.AWS_DEPLOY_ROLE_PROD`
  - `cdk deploy 'Contricool-Prod-*' --require-approval never --rollback true`
  - Output the prod CloudFront domain + prod Lambda `CodeSha256`
  - **Assert** prod `CodeSha256` == dev `CodeSha256` (passed via `needs.deploy-dev.outputs.code_sha`)
  - Write the prod CloudFront domain to SSM `/contricool/prod/cloudfront-domain` (one-shot if absent)
- [ ] **A5.** Add `smoke-prod` job:
  - `needs: deploy-prod`
  - `environment: prod`
  - Same as smoke-dev but for prod
- [ ] **A6.** Add `tag-release` job:
  - `needs: smoke-prod`
  - `environment: prod`
  - `permissions: { contents: write }` (so GITHUB_TOKEN can push tags)
  - Compute `release/YYYY-MM-DD-sha7`
  - `git tag -a` + `git push`

### Phase A tests

- [ ] **A7.** Add a tests file `apps/infra/tests/test_deploy_workflow_yaml.py`:
  - Parses `.github/workflows/deploy.yml` as YAML.
  - Asserts the five expected jobs in order with the expected `needs:` chain.
  - Asserts each AWS-touching job uses `aws-actions/configure-aws-credentials@v4` with `role-to-assume` from a `vars.AWS_DEPLOY_ROLE_*` reference (no hardcoded ARNs).
  - Asserts no `secrets.AWS_ACCESS_KEY_ID` or `secrets.AWS_SECRET_ACCESS_KEY` references anywhere in the file (red-line 1).
  - Asserts the `tag-release` job has `permissions: contents: write` and no other write scopes.

## Phase B — Author `rollback.yml`

- [ ] **B1.** Create `.github/workflows/rollback.yml` with `on: workflow_dispatch` and a single `tag` input.
- [ ] **B2.** Add `rollback` job:
  - `environment: prod` (re-uses the prod approval gate)
  - Validates the `tag` matches `release/\d{4}-\d{2}-\d{2}-[0-9a-f]{7}`
  - `git fetch --tags`
  - `git checkout ${{ inputs.tag }}` (detached HEAD, fine for build context)
  - Validates the tag is an ancestor of `main` (`git merge-base --is-ancestor`)
  - Configures AWS via OIDC with `vars.AWS_DEPLOY_ROLE_PROD`
  - `cdk deploy 'Contricool-Prod-*' --require-approval never --rollback true`
  - Smoke prod `/v1/health` with the same retry shape

### Phase B tests

- [ ] **B3.** Extend `test_deploy_workflow_yaml.py` with `test_rollback_yaml_*`:
  - Asserts `workflow_dispatch` trigger with required `tag` input.
  - Asserts the validation regex is present (so future edits can't drop it).
  - Asserts the role is `vars.AWS_DEPLOY_ROLE_PROD` and environment is `prod`.

## Phase C — Operator runbook

- [ ] **C1.** Add `specs/runbooks/rollback.md` with: when to use, prerequisites, step-by-step, troubleshooting, post-rollback actions.

## Phase D — Doc updates

- [ ] **D1.** Update `apps/infra/README.md` "First-time bootstrap" section with a pointer to: "after this PR, all subsequent deploys go through `.github/workflows/deploy.yml`."
- [ ] **D2.** Mark Phase 1d complete in `specs/EXECUTION_PLAN.md` (after the PR merges and CI is green; not in this PR — keep the markings honest).

## Verification (manual, post-merge)

These can't run inside this PR — they need the merged workflow:

- [ ] On merge to main, `deploy.yml` triggers automatically. `deploy-dev` succeeds (assuming Lambda quota covers dev's reserved=5 — current account state).
- [ ] `smoke-dev` returns 200 with the right body.
- [ ] `deploy-prod` waits for approval. After approval, deploys.
- [ ] `tag-release` creates a `release/...` tag visible in `git tag --list 'release/*'`.
- [ ] Trigger `rollback.yml` against an earlier tag → prod alias points back at the earlier image; `/v1/health` returns the earlier `version`.

## Out of scope this PR

- Adding `lambda:UpdateAlias` to the prod role for fast direct-alias-shift rollback (deferred until rollback-frequency data justifies the IAM widening).
- Slack/email failure notifications.
- Canary or weighted alias-shift rollouts.
