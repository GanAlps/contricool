# Runbook — Point-in-time restore (DDB)

## When to use

- A deploy or manual operation corrupted user data (e.g. a bad
  migration script, a bug that wrote malformed META rows).
- A rogue/leaked credential ran a destructive operation against a
  prod table.

PITR is **enabled in prod** for both Users and Transactions tables
(see `apps/infra/stacks/data_stack.py`). It rolls back to any
second within the last 35 days.

## 1. Identify the recovery point

- Open CloudTrail (audit log) and find the timestamp **just
  before** the corrupting operation. PITR rolls back to seconds
  precision; pick the latest second that's confirmed clean.

## 2. Restore to a side table

**Never** restore over a live table. Always restore to a new table
and migrate selectively.

```bash
aws dynamodb restore-table-to-point-in-time \
  --profile contricool-admin --region us-west-2 \
  --source-table-name ContriCool-Users-prod \
  --target-table-name ContriCool-Users-prod-restored-YYYYMMDD \
  --restore-date-time 2026-04-30T01:30:00Z
```

The restore takes ~5 minutes per ~10 GB.

## 3. Migrate the affected items

- Use the AWS CLI's `aws dynamodb scan + put-item` (one row at a
  time, with `ConditionExpression` to avoid stomping unrelated
  writes) to copy the affected items from the restored table back
  into the live table.
- Coordinate with users on the affected window: the live writes
  between the corrupting operation and the restore are at risk of
  being clobbered.

## 4. Drop the side table

Once verified, delete the restored table to avoid paying for
duplicate storage:

```bash
aws dynamodb delete-table \
  --profile contricool-admin --region us-west-2 \
  --table-name ContriCool-Users-prod-restored-YYYYMMDD
```

## 5. After-action

- File a runbook entry under `specs/runbooks/<date>-pitr-<table>.md`
  capturing what was restored, why, and what migration script
  reconciled the live table.
- If a deploy caused the corruption, add a CI gate that catches it
  next time (schema validation, dry-run migration).
- Update `CLAUDE.md` if the operational invariants need a change.
