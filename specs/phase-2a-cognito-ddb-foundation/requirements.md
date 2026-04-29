# Phase 2a — Cognito + DynamoDB + PII salt CDK foundation — Requirements

## Overview

Phase 2a stands up the **identity and storage substrate** that every subsequent
auth and feature task depends on. It is **infrastructure-only**: no Lambda code
changes, no client changes, no API endpoints. Once 2a is merged and deployed, a
later phase can call `boto3.cognito_idp` and `boto3.dynamodb` against real
resources in dev and prod.

This phase realises EXECUTION_PLAN.md sub-sections **2a, 2b, 2c**:

- 2a — Cognito User Pool + per-platform App Clients (no SMS, no MFA at MVP).
- 2b — `ContriCool-Users-<env>` DynamoDB table + GSI1.
- 2c — `/contricool/<env>/pii-salt` SSM SecureString.

It pulls its design from **Designs 4, 7, 13** and respects every cross-cutting
constraint locked in `CONSTRAINTS.md` (email-only auth at MVP, no phone
verification, single region us-west-2, on-demand DDB, prod-only KMS CMK,
$30/month budget envelope).

## Requirements

### R1 — Cognito User Pool per environment

A user can be created in a per-environment Cognito User Pool that:

- Has the pool name `contricool-<env>` (`contricool-dev`, `contricool-prod`).
- Treats `email` as a **standard, required, verified** sign-in attribute. Sign-in
  uses `email` (case-insensitive); the auto-generated `sub` is never exposed.
- Treats `name` as a standard, required, mutable attribute.
- Treats `phone_number` as **optional, NOT verified**. If present at signup or
  in `PATCH /v1/me`, the value is format-validated as E.164. Phone is **never**
  used for login, recovery, friend search, or any other identity flow at MVP.
- Has exactly **one custom attribute**: `custom:user_id` — string, max 26 (ULID
  shape). Application data in DynamoDB keys by this ULID, not by Cognito's
  `sub`.
- Enforces a password policy of: **min 10 chars, ≥1 number, ≥1 lowercase, ≥1
  uppercase, ≥1 symbol**, password history 3.
- Sends verification + forgot-password emails via Cognito's **managed sender**
  (`no-reply@verificationemail.com`) at MVP — no SES domain identity is used.
  Friendly-from name is `ContriCool`.
- Has **no SMS configuration** — the pool is configured for `EmailMessage` and
  `EmailSubject` only. No SNS role is attached.
- Has **no MFA**.

### R2 — Per-platform App Clients

For each user pool, three App Clients exist:

| Client name | Platform | Secret? | Allowed flows | Refresh-token validity | Access token validity |
|---|---|---|---|---|---|
| `web` | Expo web | no | `USER_SRP_AUTH`, `REFRESH_TOKEN_AUTH` | 30 days | 1 hour |
| `ios` | iOS app | no | `USER_SRP_AUTH`, `REFRESH_TOKEN_AUTH` | 30 days | 1 hour |
| `android` | Android app | no | `USER_SRP_AUTH`, `REFRESH_TOKEN_AUTH` | 30 days | 1 hour |

ID-token validity is 1 hour (matches access token, mandated by Cognito).
Token-revocation is enabled on every client (so `/v1/auth/logout` works).

### R3 — `ContriCool-Users-<env>` DynamoDB table

A table named `ContriCool-Users-<env>` exists per environment with:

- **PK** `string`, **SK** `string` (composite primary key).
- **One GSI** named `GSI1`: `GSI1PK` `string` partition, `GSI1SK` `string` sort.
  GSI1 projects **all attributes** (Design 7 requires META profile attributes
  on the email-lookup index hit).
- **Billing**: PAY_PER_REQUEST (on-demand) — matches CONSTRAINTS.md budget.
- **PITR**: enabled in prod, disabled in dev (cost-minimal; dev data is
  ephemeral).
- **DDB Streams**: enabled in **prod only** with `NEW_AND_OLD_IMAGES`. No
  consumer at MVP — this is forward-prep for Phase 6 (audit fan-out / future
  notifications).
- **Encryption**:
  - dev: AWS-managed key (`alias/aws/dynamodb`) — free tier.
  - prod: customer-managed CMK `alias/contricool-prod` (already exists in
    `Contricool-Shared`).
- **TTL attribute**: `ttl` (number) — used by `RATE#` rows and (future)
  `IDEMPOTENCY#` rows.
- **Removal policy**: `RETAIN` in prod (never lose user data), `DESTROY` in dev
  (so a teardown leaves a clean account).

### R4 — `/contricool/<env>/pii-salt` SSM SecureString

A per-environment SSM SecureString parameter named `/contricool/<env>/pii-salt`
exists with:

- **Value**: 32-byte cryptographically random hex string. Generated **once**
  per environment by a CDK custom resource on first deploy and **never
  rotated** thereafter (rotation breaks every email lookup hash). On subsequent
  deploys the custom resource MUST be a no-op — it must NOT regenerate or
  overwrite the value.
- **KMS encryption**: `alias/contricool-prod` in prod; AWS-managed
  `alias/aws/ssm` in dev.
- **Access control**: only the API Lambda's execution role (added in Phase 2c)
  is allowed `ssm:GetParameter` + `kms:Decrypt` on this parameter. Deploy
  roles MAY read but MUST NOT delete or overwrite (the no-rotation rule is
  permission-enforced as well).

### R5 — CDK structure

- **New stacks**: `Contricool-{Dev,Prod}-Auth` and `Contricool-{Dev,Prod}-Data`.
  Auth holds the Cognito User Pool + App Clients + SSM Parameter for the salt.
  Data holds the Users DDB table.
- **app.py** wires both new stacks into the existing per-env loop and tags them
  with `env=<env>`. Project-wide `app=contricool` tag still applies via the
  app-level `cdk.Tags.of(app)`.
- **No reads of new resources by existing stacks** — the Api stack does not
  yet need the User Pool ID or table name; that wiring lands in Phase 2b/2c.
- The CDK SecurityAspect MUST continue to pass (BlockPublicAccess on every
  bucket; reserved-concurrency on every Lambda). Adding new stacks must not
  introduce any new uncovered Lambda or bucket.

### R6 — CDK outputs published

`CfnOutput`s exposed for downstream phases (consumed at Lambda cold start via
SSM Parameter Store reads — **never embedded in client code or committed to
source**, per CLAUDE.md red-line 1):

- `Contricool-<env>-Auth.UserPoolId`.
- `Contricool-<env>-Auth.WebClientId`, `IosClientId`, `AndroidClientId`.
- `Contricool-<env>-Data.UsersTableName`, `UsersTableArn`.

After deploy, the GitHub Actions deploy workflow (or a one-shot script) writes
these to SSM under `/contricool/<env>/cognito/...` + `/contricool/<env>/ddb/...`.
Phase 2b/2c reads them at Lambda cold start via `ssm:GetParameter`.

### R7 — Tests

Synth-time tests in `apps/infra/tests/test_synth.py` cover:

- Pool name, sign-in alias, password policy, custom attribute schema, MFA off,
  email-only verification (no SMS configuration on the pool).
- Three app clients per pool, no secret, USER_SRP_AUTH + REFRESH_TOKEN_AUTH only.
- Users table key shape, GSI1 key shape, TTL attribute, billing mode.
- PITR + Streams + KMS CMK enabled in **prod only**.
- SSM parameter has SecureString type and CMK KeyId in prod.
- Aspect still passes for the new stacks.

### R8 — Deploy + verification

- The Phase 2a PR merges to `main` and the existing `deploy.yml` pipeline rolls
  it through dev → smoke → prod (no deploy.yml changes needed; the
  `'Contricool-Dev-*'` glob already picks up the new stacks).
- After dev deploy: `aws cognito-idp describe-user-pool --user-pool-id $ID`
  returns the pool with the expected schema. `aws dynamodb describe-table
  --table-name ContriCool-Users-dev` returns the table with on-demand billing.
  `aws ssm get-parameter --name /contricool/dev/pii-salt --with-decryption`
  returns a 64-char hex string.
- Same checks against prod after the manual gate.
- `gitleaks` clean — no IDs, ARNs, account numbers committed.

### R9 — Out of scope (forward links)

- Cognito User Pool **triggers** (PreSignUp, PostConfirmation Lambda) — Phase 2c.
- API Gateway JWT Authorizer pointed at the pool — Phase 2c (when there are
  protected routes worth gating).
- ContriCool-Transactions table — Phase 4.
- Phone-related GSI2 — deferred until phone verification is reintroduced
  post-MVP (CONSTRAINTS.md "Path to re-introduce phone verification").

## Edge cases

- **Salt generation determinism**: the CDK custom resource MUST emit the same
  parameter value on every subsequent deploy. Using `random.token_hex(32)`
  inside the custom resource handler would regenerate on every update; the
  handler MUST detect "parameter already exists" and return the existing value
  unchanged. CloudFormation `Update` events MUST be no-ops.
- **Pool deletion**: a `cdk destroy` against the prod Auth stack must NOT
  delete the User Pool (`removal_policy=RETAIN`). Otherwise a `cdk destroy`
  followed by a re-deploy creates a new pool with new IDs and orphans every
  user account.
- **CFN export naming**: stack outputs marked `export_name` participate in
  cross-stack imports. We do NOT use `export_name` for User Pool / Client /
  Table identifiers — Phase 2c reads them via SSM at Lambda runtime, not via
  CFN imports. Cross-stack imports would wedge prod refactors later.

## Summary

Phase 2a delivers the Cognito + DDB Users + PII salt foundation. After merge:
both environments host an empty User Pool, an empty Users table, and a
generated salt. No user-facing change yet; everything is plumbing for Phases
2b–2e.
