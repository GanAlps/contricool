# Phase 4a — Transactions DDB Table — Requirements

## Overview

Phase 4a stands up the **`ContriCool-Transactions-<env>`** DynamoDB table — the
financial-ledger half of the two-table model defined in `specs/07-database-data-model/design.md`.
It is **infrastructure-only**: no Lambda code changes, no client changes, no
API endpoints. Once 4a is merged and deployed, an empty Transactions table
exists in dev and prod. Phase 4b wires the API Lambda to read/write it.

This phase realises **EXECUTION_PLAN.md sub-section 4a** ("Transactions DDB
table (CDK Data stack)").

The decision to ship the table on its own — separate from the backend feature
— mirrors the Phase 2a → 2b/2c split: foundation infrastructure lands first as
a small, low-risk PR; feature code that depends on it follows in a later PR
once the table exists in both environments.

## Requirements

### R1 — `ContriCool-Transactions-<env>` table

A table named `ContriCool-Transactions-<env>` exists per environment with:

- **PK** `string`, **SK** `string` (composite primary key).
- **One GSI** named `GSI1`: `GSI1PK` `string` partition, `GSI1SK` `string`
  sort, `ProjectionType.ALL`. (Used by Pattern #8 from Design 7: "list
  transactions where user is a member, by date desc". `ProjectionType.ALL`
  lets `META` rows return without a follow-up `BatchGetItem` round-trip.)
- **Billing**: `PAY_PER_REQUEST` (on-demand) — matches the budget envelope in
  `CONSTRAINTS.md`.
- **PITR**: enabled in **prod only**, disabled in dev (cost-minimal; dev data
  is ephemeral and recreatable).
- **DDB Streams**: enabled in **prod only** with `NEW_AND_OLD_IMAGES`. No
  consumer at MVP — forward-prep for Phase 6 (audit fan-out).
- **Encryption**:
  - dev: AWS-managed key (`alias/aws/dynamodb`) — free tier.
  - prod: customer-managed CMK `alias/contricool-prod` (already exists in
    `Contricool-Shared`, same key the Users table uses).
- **TTL attribute**: `ttl` (number) — used by `IDEMPOTENCY#<user>#<key>` rows
  written by the Powertools idempotency decorator in Phase 4b.
- **Removal policy**: `RETAIN` in prod (never lose financial data),
  `DESTROY` in dev (so a teardown leaves a clean account).
- **Deletion protection**: enabled in prod.

### R2 — CDK structure

- **Same stack**: the Transactions table extends the existing
  `Contricool-{Dev,Prod}-Data` stack — no new stack. Both DDB tables share
  one stack so they share one KMS-grant boundary in prod and one PITR/Stream
  toggle.
- **Same constructor**: `DataStack` keeps its existing parameters
  (`env_name`, `prod_cmk`); the Transactions table is created alongside the
  Users table inside `__init__`.
- **`app.py`**: no changes required to wire the new table — the existing
  `data = DataStack(...)` call already covers it. Phase 4b will add a
  `transactions_table=data.transactions_table` kwarg to the `ApiStack`
  constructor when the API code lands.
- **No reads of the new table by other stacks** — the Api stack does not
  yet need the table name. Phase 4b is responsible for that wiring (mirrors
  Phase 2a → 2c).

### R3 — CDK outputs

`CfnOutput`s exposed for downstream phases (consumed at Lambda cold start via
SSM Parameter Store reads — never embedded in client code or committed to
source, per CLAUDE.md red-line 1):

- `Contricool-<env>-Data.TransactionsTableName`.
- `Contricool-<env>-Data.TransactionsTableArn`.
- `Contricool-<env>-Data.TransactionsTableStreamArn` — **prod only**, mirrors
  the Users-table pattern. If prod has Streams enabled but the synthesised
  ARN is `None`, synth must fail (a silent CDK regression that drops the
  StreamSpecification has bitten this stack before).

After deploy, the GitHub Actions deploy workflow (or one-shot script) writes
these to SSM under `/contricool/<env>/ddb/transactions-table-name` and
`/contricool/<env>/ddb/transactions-table-arn`. Phase 4b reads them at Lambda
cold start via the existing `ssm:GetParameters` call.

### R4 — Synth tests

Add tests to `apps/infra/tests/test_synth.py` covering:

- Two tables synthesise from `DataStack` (was 1, now 2). Both are
  `PAY_PER_REQUEST` with TTL attr `ttl`.
- Transactions table key shape: `PK`/`SK` HASH/RANGE; attribute defs include
  `GSI1PK`/`GSI1SK` of type `S`.
- Transactions table GSI1: `GSI1PK`/`GSI1SK` HASH/RANGE, `ProjectionType=ALL`.
- PITR + Streams enabled on Transactions table in **prod only** (and absent
  in dev).
- Prod uses the customer-managed CMK; dev does not specify
  `KMSMasterKeyId`.
- Prod table has `DeletionPolicy=Retain` and `DeletionProtectionEnabled=True`;
  dev has `DeletionPolicy=Delete`.
- The `SecurityAspect` still passes — no new Lambdas or buckets introduced.

### R5 — Deploy + verification

- The Phase 4a PR merges to `main`; the existing `deploy.yml` pipeline rolls
  it through dev → smoke → prod (no deploy.yml changes needed; the
  `Contricool-Dev-*` glob already picks up the additional table inside the
  Data stack).
- After dev deploy: `aws dynamodb describe-table --table-name
  ContriCool-Transactions-dev` returns the table with on-demand billing,
  GSI1, and TTL configured.
- Same checks against prod after the manual gate. Prod additionally shows
  PITR enabled, Streams enabled, and the customer-managed CMK ARN.
- `gitleaks` clean — no IDs, ARNs, account numbers committed.

### R6 — Out of scope (forward links)

- `transactions` feature backend (`apps/api/app/features/transactions/`),
  routes, splits math, balance computation, idempotency decorator → **Phase 4b**.
- API stack IAM grants on the new table (`GetItem`, `PutItem`, `Query`,
  `TransactWriteItems`, etc.) → **Phase 4b**, alongside the API code that
  needs them.
- Frontend transaction UI → **Phase 4c**.
- Audit-row fan-out via Streams (consumer Lambda) → **Phase 6**.

## Edge cases

- **CDK silently drops `StreamSpecification`**: an earlier prod-Users
  refactor lost the `StreamSpecification` block. The R3 assertion ("prod
  has streams enabled but `table_stream_arn` is None → synth fails") is the
  same backstop applied to the new table.
- **Prod table deletion**: a `cdk destroy` against the prod Data stack must
  NOT delete the Transactions table (`removal_policy=RETAIN`,
  `deletion_protection=True`). Otherwise destroy + redeploy creates a new
  empty table and orphans every transaction row.
- **CFN export naming**: stack outputs marked `export_name` participate in
  cross-stack imports. We do NOT use `export_name` for the Transactions
  table identifiers — Phase 4b reads them via SSM at Lambda runtime, not
  via CFN imports. Cross-stack imports would wedge prod refactors later.

## Summary

Phase 4a delivers an empty `ContriCool-Transactions-<env>` table in both
environments and exposes its name + ARN as CfnOutputs for Phase 4b to
consume via SSM. No user-facing change yet; everything is plumbing for the
transactions feature.
