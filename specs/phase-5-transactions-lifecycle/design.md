# Phase 5 — Transactions Lifecycle — Design

**Complexity: MEDIUM-to-COMPLEX.** Backend gets three new
endpoints with TransactWriteItems + per-write AUDIT; frontend gets
an edit modal (re-using the Phase 4c AddTransactionSheet shape) and
optimistic delete + undo. Cleanup Lambda is small but new.

## Overview

Phase 5 closes the transaction CRUD gap: creator can **edit**,
**soft-delete**, or **restore** their own transactions, with a
30-day grace window before hard-delete. Every mutation writes an
AUDIT row capturing the prior META + MEMBER snapshot.

## Backend

### New errors (`errors.py`)

| Class | Code | HTTP |
|---|---|---|
| `ForbiddenError` | `FORBIDDEN` | 403 |
| `PreconditionFailedError` | `PRECONDITION_FAILED` | 412 |
| `GoneError` | `GONE` | 410 |

### New routes (`routes.py`)

| Method | Path | Notes |
|---|---|---|
| `PUT` | `/v1/transactions/{txn_id}` | `If-Match: <updated_at>` header required (412 on stale). Body shape mirrors `CreateTransactionRequest` minus `currency` (immutable). |
| `DELETE` | `/v1/transactions/{txn_id}` | Soft delete; sets `deleted_at`. Idempotent — second DELETE returns 204 with no AUDIT. |
| `POST` | `/v1/transactions/{txn_id}/restore` | Clears `deleted_at` if within 30 days. 410 GONE after window. |

All three are creator-only (403 to non-creator member, 404-mask to
non-member).

### Service additions

- `update_transaction(requester_id, txn_id, body, if_match)`:
  1. Read META; 404-mask if missing or non-member.
  2. 403 if `creator_id != requester_id`.
  3. 412 if `if_match != updated_at`.
  4. Same validation as create (members, currencies, friendships,
     splits, payers, amounts, settlement shape).
  5. `repo.update_transaction(...)` — TransactWriteItems with:
     - friendship `ConditionCheck`s for new other-members,
     - `Update` on META (with `updated_at = :now` precondition on
       both old `updated_at` and `creator_id`),
     - `Delete` on prior MEMBER rows + `Put` on new MEMBER rows
       (members may have changed),
     - `Put` AUDIT row (`action=update`, prior snapshot).
- `delete_transaction(requester_id, txn_id)`:
  1. Read META; 404-mask if missing or non-member.
  2. 403 if not creator.
  3. If already deleted: return idempotent 204 (no AUDIT).
  4. `repo.soft_delete_transaction(...)` — Update META setting
     `deleted_at` + `updated_at`; Put AUDIT (`action=delete`).
- `restore_transaction(requester_id, txn_id)`:
  1. Read META; 404-mask if missing or non-member.
  2. 403 if not creator.
  3. 422 if `deleted_at` is null (nothing to restore).
  4. 410 GONE if `now - deleted_at > 30 days`.
  5. `repo.restore_transaction(...)` — Update META clearing
     `deleted_at` + bumping `updated_at`; Put AUDIT
     (`action=restore`).

### Repository additions

Three TransactWriteItems flows. Each records an AUDIT row with the
**prior** snapshot so a post-hoc reader can reconstruct any state.

### Cleanup Lambda

`apps/api/app/cleanup/main.py` — handler invoked via EventBridge
once per day. For each TXN with `deleted_at < now - 30d`:
- Hard-delete META + MEMBER rows.
- Mark AUDIT rows for that txn with `ttl = audit_at + 90d` so DDB
  TTL purges them post-grace.

CDK additions: a new Python `lambda_function.PythonFunction` (small
reserved-concurrency = 1) + `EventBridge.Rule(schedule=cron("0 2 *
* ? *"))`. IAM scoped to `dynamodb:Query`, `BatchWriteItem`,
`UpdateItem` on the Transactions table only.

## Frontend

### Detail page (`(app)/transactions/[txnId].tsx`)

- Edit + Delete buttons: only render when `meta.creator_id === me.user_id`.
- "Edit" → opens `AddTransactionSheet` in **edit mode** (new prop
  `existing?: Transaction`). Pre-fills all fields. On submit, calls
  `useUpdateTransaction` with `If-Match: existing.updated_at`.
- "Delete" → optimistic: queryClient removes from list cache,
  toast appears with "Undo" action (5s window). On undo: re-add
  to cache, no API call. On timeout: fire DELETE.
- 412 `PRECONDITION_FAILED` on edit → banner "Someone else changed
  this. Refresh and try again."
- 403 `FORBIDDEN` on edit/delete → banner "You can't edit/delete
  this transaction."

### Hooks (`lib/queries/transactions.ts`)

```ts
useUpdateTransaction()  // PUT
useDeleteTransaction()  // DELETE — supports optimistic via onMutate
useRestoreTransaction() // POST :restore
```

### Tests

- AddTransactionSheet edit-mode: pre-fills, sends `If-Match`,
  surfaces 412 banner.
- Detail page: hides buttons for non-creator; tap Delete → toast +
  Undo; undo cancels mutation.
- All N1–N12 negatives have inline mocks per scenario.

## Cleanup Lambda

Tiny. EventBridge cron `0 2 * * ? *` (UTC). Single query against
GSI1 reverse — actually we don't have an index on `deleted_at`, so
the cleanup uses a Scan with a filter on `deleted_at` capped at the
relevant page size (since soft-deletes are rare, scan cost is
negligible at MVP). For each candidate, BatchWriteItem to delete
META + MEMBER rows; Update each AUDIT row's `ttl` to `now + 90d`.

## Summary

Three endpoints + cleanup + edit modal + delete UX. Single PR.
Tests across the negatives. Coverage stays at 99% for backend and
existing thresholds for client.
