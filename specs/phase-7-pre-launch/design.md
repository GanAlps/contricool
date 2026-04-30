# Phase 7 — Pre-Launch Polish — Design

## Overview

Ship-ready surface: account deletion + export, cleanup Lambda
finally wired up, legal pages, security review, launch runbook.
All in one PR per the user's request. Custom domain, WAF, and
synthetic load probe are deferred (decided 2026-04-30).

## Backend

### `DELETE /v1/me` — soft account deletion

- **Auth**: requester's id token.
- **Effect**:
  1. Update Users META row: `status = "deactivated"`, set `deactivated_at`.
  2. Cognito `AdminDisableUser` + `AdminUserGlobalSignOut` so existing
     refresh tokens stop working.
  3. Return 204.
- **Errors**: 401 unauth.
- **Idempotent**: second call returns 204 with no extra DDB write.
- The user can re-activate within 30 days by signing back in IF
  Cognito is re-enabled — but Cognito disable is sticky, so practically
  the user contacts support to undo. (No self-service reactivation
  endpoint at MVP.)

### `GET /v1/me/export` — JSON dump of own data

- **Auth**: requester's id token.
- **Body**: `{ user, friendships, transactions: [...full Transaction shape...] }`.
- **Rate limit**: 1 export per 24 hours per user. Reuses the
  Phase 2c rate-limit table with a new `EXPORT_RATE` row class.
- **Errors**: 429 `RATE_LIMITED`.

### Cleanup Lambda — wire up

The Phase 5 follow-up. Composes:
- **Soft-deleted transactions** (existing logic) — hard-delete
  META + MEMBER rows after 30 d; mark AUDIT rows with 90 d TTL.
- **Deactivated accounts** (new) — for users with
  `status = deactivated` and `deactivated_at < now - 30d`:
  1. Hard-delete the Users META row + the email-hash GSI projection.
  2. Anonymize the user's appearance in any remaining transactions
     (replace `user_id` with `DELETED#<random>`, drop `name` from
     audit snapshots).
  3. `AdminDeleteUser` in Cognito.
- **CDK construct**:
  - `lambda_python_alpha.PythonFunction` (zip-packaged, separate
    from the API container).
  - Reserved concurrency = 1 (only one cleanup pass per minute,
    triggered by EventBridge cron daily).
  - IAM: scoped to `dynamodb:Scan/UpdateItem/BatchWriteItem` on
    Users + Transactions tables, `cognito-idp:AdminDeleteUser` on
    the env's pool. No `*` actions.
  - EventBridge `Schedule(cron("0 2 * * ? *"))` UTC.

## Frontend

### `/privacy` + `/terms`

- Static markdown-derived pages under `app/(public)/privacy.tsx`
  and `app/(public)/terms.tsx`. Reachable when logged out.
- Content drafted to cover CCPA + India DPDP basics: data
  collected, purposes, retention, deletion rights, grievance
  officer contact (your email).

### `/settings` (`(app)/settings.tsx`)

- Top-bar nav adds a **Settings** link.
- Sections:
  - **Account** — display email, currency, name. "Delete my
    account" button → confirm → `DELETE /v1/me` → log out.
  - **Data** — "Export my data" button → `GET /v1/me/export` →
    save as JSON.
  - **Legal** — links to `/privacy` and `/terms`.

### Hooks

- `useDeleteMyAccount()` — mutation; on success clears auth store.
- `useExportMyData()` — mutation; on success triggers JSON download.

## Documentation

- Root `README.md` — usage, deploy, design link.
- `specs/runbooks/launch.md` — go/no-go checklist:
  - All Phase 0–7 tests green in CI.
  - Backend coverage ≥ 99%.
  - Privacy + Terms pages reviewed.
  - Cleanup Lambda fired at least once successfully.
  - Negative-test suite re-run end-to-end against dev.
  - Latest CloudWatch dashboard reviewed; no chronic 4xx from real
    users.
  - SMS spend MTD < $1 (no abnormal signup volume).

## Security review (pure-test)

New tests (no production code):

- `test_cdk_aspect_block_public_access_on_every_bucket.py` — synth +
  assert.
- `test_cdk_no_wildcard_iam_action_on_lambda_role.py` — synth +
  assert.
- `test_cdk_strict_response_headers_present.py` — assert HSTS,
  CSP, X-Content-Type-Options, Referrer-Policy on the CloudFront
  response-headers policy.

## Out of scope

- Custom domain / SES (decided no).
- WAF (decided no — risks bounded by existing cost guardrails).
- Synthetic load probe (decided no — premature at MVP scale).
