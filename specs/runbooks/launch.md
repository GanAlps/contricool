# Launch — go/no-go checklist

Use this list before flipping ContriCool from "internal preview" to "publicly invited
testers". Run top-to-bottom; do not start the next group until the current one is green.

## Pre-flight (T-7 days)

- [ ] All Phase 7 items merged to `main`; `EXECUTION_PLAN.md` shows Phase 7 complete.
- [ ] No open `pr-code-reviewer` blocking comments on the last 5 PRs.
- [ ] No high or critical findings in the latest Dependabot scan.
- [ ] No findings in the latest gitleaks scan (`pnpm exec lefthook run pre-commit`).
- [ ] AWS Budget alert at $20 (warn) and $30 (critical) is firing-tested (lower the
      threshold to $0.01, observe alarm, restore).
- [ ] SNS SMS account spend cap is configured at $5 (Service Quotas → SNS).
- [ ] Lambda reserved concurrency: dev=5, prod=100 — confirm in console.
- [ ] DDB PITR enabled on both Users and Transactions tables in prod.

## Privacy and legal

- [ ] `/privacy` renders with effective date.
- [ ] `/terms` renders with effective date.
- [ ] Both pages are linked from Settings and from the signup screen.
- [ ] Support email (`support@contricool.app`) is monitored or auto-replies.

## Account lifecycle

- [ ] `DELETE /v1/me` deactivates a real test user end-to-end:
  - [ ] User row goes `status=deactivated` with `deactivated_at` and `email_for_cleanup`.
  - [ ] Cognito user is disabled and globally signed out.
  - [ ] Subsequent API calls return 401.
- [ ] `GET /v1/me/export` returns a 200 JSON payload with the user's transactions and
      friends; second call within 24 h returns 429 with `retry_after_seconds`.
- [ ] Cleanup Lambda (manually invoked once) hard-deletes a deactivated user backdated
      31 days, deletes friendship rows, and removes the Cognito user.

## Observability

- [ ] CloudWatch dashboard "ContriCool-API" shows traffic for the last hour.
- [ ] Alarms fire on synthetic 5xx spike (force a 500 from a non-prod env, observe alarm).
- [ ] SES bounce > 5% alarm has a target SNS topic with a working email subscriber.

## Performance smoke

- [ ] Manual smoke against dev:
  - [ ] Sign up → verify email → log in → dashboard renders < 2 s on a cold viewer.
  - [ ] Add a friend, add a transaction, edit it, delete it, restore it.
- [ ] No console errors in the browser DevTools during the smoke flow.
- [ ] Lighthouse a11y score >= 90 on the dashboard and add-transaction sheet.

## Post-launch (T+0 to T+24 h)

- [ ] First hour: watch the alarms dashboard live; investigate any breach immediately.
- [ ] First day: review CloudWatch Logs Insights for unusual error patterns.
- [ ] First week: review AWS Budgets MTD; ensure spend trajectory is well under $30.
