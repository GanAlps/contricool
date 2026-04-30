# Runbook — API 5xx alarm fires

**Alarm**: `contricool-prod-apigw-5xx` or
`contricool-prod-lambda-errors`. Composite `contricool-prod-site-is-down`
fires when either is in alarm. SNS routes the composite to email +
SMS; the individual alarms route to email only.

## 1. Confirm

1. Open the **Prod dashboard**: CloudWatch → Dashboards →
   `ContriCool-Prod-Health`. Look at the "API Gateway 4xx / 5xx"
   widget — is the spike still active or recovering?
2. Check the [`5xx-in-last-hour`](#) saved Logs Insights query
   (Logs Insights → Saved queries → `contricool/prod/5xx-in-last-hour`)
   to find the affected paths + request_ids.

## 2. Triage

- **Single path**: a recent deploy may have regressed it. Check
  the latest Deploy run on `main`. If the regression is recent,
  trigger the **rollback workflow** (see `runbook-rollback.md`).
- **All paths**: cold-start surge or downstream outage. Check:
  - Lambda Init Duration (is the function freshly cold-starting?)
  - DDB ThrottledRequests on Users + Transactions tables.
  - Cognito InitiateAuth metrics.
- **Trickle (1–2 / 5 min)**: not site-down. Tag the request_ids in
  Slack and triage when convenient.

## 3. Mitigate

- **Recent regression**: rollback. After rollback, file an issue
  with the request_id + 5xx body so the fix can land properly.
- **Capacity**: bump `reserved_concurrent_executions` in
  `apps/infra/app.py` if Lambda Throttles are firing. PR + deploy
  through the normal gate.
- **Downstream outage**: there's nothing you can do server-side.
  Post a status update to the user-facing notice channel and wait.

## 4. After-action

- Add the failure mode to `tests/features/<feature>/test_*.py` if
  not already covered.
- Update this runbook if the steps were inadequate.
