# Phase 4a — Transactions DDB Table — Tasks

Each task is independently completable and ordered by dependency. Tests live
in the same phase as the code that produced them (per
`~/.claude/DEVELOPMENT.md`).

## Phase 4a — single phase, infra only

### T1 — Lift `encryption_kwargs` out of `DataStack` for shared use

- File: `apps/infra/stacks/data_stack.py`
- Move the `encryption_kwargs` block (currently constructed inline before
  the Users table) so both tables read from one local variable. No
  behaviour change.
- Acceptance: `pytest tests/test_synth.py::test_data_stack_table_keys_billing_ttl`
  still passes (Users table shape unchanged).

### T2 — Add `transactions_table` construct + GSI1 to `DataStack`

- File: `apps/infra/stacks/data_stack.py`
- Add `self.transactions_table = dynamodb.Table(...)` with the schema in
  `design.md` §"CDK Implementation".
- Add `add_global_secondary_index` for `GSI1` (`GSI1PK`/`GSI1SK`,
  `ProjectionType.ALL`).
- Acceptance: `cd apps/infra && cdk synth Contricool-Dev-Data` produces a
  template with two `AWS::DynamoDB::Table` resources.

### T3 — Add CfnOutputs for the new table

- File: `apps/infra/stacks/data_stack.py`
- `TransactionsTableName`, `TransactionsTableArn`, and (prod only)
  `TransactionsTableStreamArn` with the same null-stream-arn assertion
  used for the Users table.
- Acceptance: synth output template lists three `Outputs` for prod and two
  for dev.

### T4 — Update `DataStack` module docstring

- File: `apps/infra/stacks/data_stack.py`
- Drop the "Phase 4 will add a separate Data stack — Transactions — or
  extend this stack with a second table" forward-link; replace it with a
  factual description of the two tables now in scope.

### T5 — Synth tests for the Transactions table

- File: `apps/infra/tests/test_synth.py`
- Add the six tests listed in `design.md` §"Tests".
- Update the existing `test_data_stack_table_keys_billing_ttl` and
  `test_data_stack_pitr_streams_only_in_prod` if they assume
  `len(tables) == 1` — they must accept two tables and locate the Users
  table by `TableName`.
- Acceptance: `cd apps/infra && pytest tests/test_synth.py -k data_stack`
  green.

### T6 — Run full infra test suite + cdk synth

- Acceptance:
  - `cd apps/infra && pytest tests/ -q` green.
  - `cd apps/infra && cdk synth --all` exits 0 (no aspect failures).
  - `cd apps/infra && cdk diff Contricool-Dev-Data` shows ONLY a new table
    + new outputs (no deletes, no Users-table mutations).

### T7 — Update `EXECUTION_PLAN.md`

- File: `specs/EXECUTION_PLAN.md`
- Mark Phase 4a as ✅ COMPLETE in the sub-phase rollout table once the PR
  is open (matches the Phase 2/3 convention of marking-on-PR).
- Add a row in the Phase 4 sub-phase table linking to
  `specs/phase-4a-transactions-table/`.

### T8 — Open PR `feat/phase-4a-transactions-table`

- Branch off `main`.
- Squash-merge enabled by default.
- Conventional Commit on the squash: `feat(infra): Phase 4a — Transactions
  DDB table (Data stack)`.
- PR body links the spec folder.
- Wait for CI green (lint, test, cdk-diff, openapi-check, gitleaks).

## Out of scope for 4a (forward links)

- Granting Lambda IAM actions on the new table → Phase 4b.
- Wiring `transactions_table` into `ApiStack` constructor → Phase 4b.
- Writing the SSM parameters for table-name/arn after deploy → covered by
  the existing post-deploy SSM-write step in Phase 4b's deploy notes.
- Backend `transactions` feature → Phase 4b.
- Frontend transaction UI → Phase 4c.
