# Runbook — Rollback a bad deploy

## When to rollback

- The `Deploy` workflow's smoke step failed → no rollback needed,
  the deploy didn't complete.
- The `Deploy` workflow's smoke succeeded but a regression surfaced
  later (the 5xx alarm fired, a customer reported a broken flow,
  etc.) → rollback.

## 1. Run the rollback workflow

1. GitHub → Actions → `Rollback` workflow.
2. Click **Run workflow**. The form asks:
   - **environment**: `dev` or `prod`.
   - **target_version**: leave blank to revert to the version one
     before the current `live` alias, or paste a specific Lambda
     version number.
3. Click **Run**.

The workflow re-points the Lambda's `live` alias at the previous
published version. **It does NOT redeploy the container image** —
prior versions are pinned by digest, so the rollback is byte-for-
byte identical to what was running before.

## 2. Confirm

- CloudWatch → Lambda → `contricool-api-<env>` → Aliases →
  `live`. Confirm the version it points to is the one you intended.
- Watch the next 5 minutes of `apigw-5xx` and `lambda-errors`
  metrics — they should fall back to baseline.

## 3. After-action

- File an issue with the bad commit SHA and the symptom.
- Add a regression test in the relevant feature's test suite.
- Re-deploy the fix through the normal pipeline.

## Limitations

- Rollback only handles the **API Lambda image**. CloudFront-served
  client bundle changes are not auto-rolled back; if the regression
  is in the client, revert the offending commit on `main` and
  re-deploy.
- Rollback **cannot recover from a destructive DDB schema change**
  (e.g. a bad migration that wrote bad data). For data integrity
  issues, see `runbook-pitr-restore.md`.
