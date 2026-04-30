# Phase 5 — Transactions Lifecycle — Requirements

## In scope

- **R1** — Creator can edit any of their own transactions via
  `PUT /v1/transactions/{txn_id}` with `If-Match: <updated_at>`.
  Stale `If-Match` → 412 `PRECONDITION_FAILED`. Re-validation
  matches the create-time invariants (members, currency, friendships,
  splits, payers, amounts, settlement shape).
- **R2** — Creator can soft-delete any of their own transactions via
  `DELETE /v1/transactions/{txn_id}`. Sets `deleted_at`. Idempotent
  — second call is a 204 no-op.
- **R3** — Creator can restore a soft-deleted transaction within
  30 days via `POST /v1/transactions/{txn_id}/restore`. Past
  30 days → 410 `GONE`.
- **R4** — Every mutation (create / update / delete / restore)
  writes an AUDIT row with the prior META + MEMBER snapshot.
- **R5** — Soft-deleted transactions are excluded from default list
  queries and from balance computation.
- **R6** — Daily cleanup pass: hard-delete META + MEMBER rows of
  transactions whose `deleted_at` is more than 30 days old; mark
  AUDIT rows for those transactions with a 90-day TTL so DDB purges
  them post-grace.
- **R7** — Detail page shows Edit + Delete buttons only when the
  requester is the creator. AddTransactionSheet supports edit-mode
  (`existing` prop) and PUTs with `If-Match`. Detail page shows a
  Restore bar when the txn is soft-deleted.

## Negatives (CLAUDE.md red-line 3 — every auth/security invariant
covered by a negative test)

| # | Scenario | Expected |
|---|---|---|
| N1 | Edit as non-creator member | 403 `FORBIDDEN` |
| N2 | Edit as non-member | 404 (mask) |
| N3 | Edit with stale `If-Match` | 412 `PRECONDITION_FAILED` |
| N4 | Edit removing self from members | 422 `SELF_NOT_MEMBER` |
| N5 | Edit with new non-friend member | 422 `NOT_FRIEND` |
| N6 | Edit changing currency | 422 `CURRENCY_MISMATCH` |
| N7 | Edit missing `If-Match` header | 422 `VALIDATION_ERROR` |
| N8 | Edit unauthenticated | 401 |
| N9 | Delete as non-creator | 403 |
| N10 | Delete as non-member | 404 |
| N11 | Delete unauthenticated | 401 |
| N12 | Soft-deleted txn excluded from list | confirmed |
| N13 | Soft-deleted txn excluded from balance | confirmed |
| N14 | Restore non-deleted txn | 422 `NOT_DELETED` |
| N15 | Restore as non-creator | 403 |
| N16 | Restore as non-member | 404 |
| N17 | Restore past 30 days | 410 `GONE` |
| N18 | Restore unknown txn | 404 |
| N19 | Restore unauthenticated | 401 |
| N20 | Frontend hides edit/delete for non-creator | UI |
| N21 | 412 PRECONDITION_FAILED on edit surfaces refresh banner | UI |
| N22 | GONE on restore surfaces 30-day expired toast | UI |

## Out of scope (this phase)

- **CDK wire-up of the cleanup Lambda** — the cleanup module +
  comprehensive tests ship in this PR; the EventBridge schedule +
  separate IAM-scoped Lambda construct is a one-construct follow-up.
  Soft-deletes accumulate harmlessly in DDB until then; the Restore
  endpoint and the 30-day mask both work without the cleanup having
  ever fired.
- **Edit form full UX polish** — the AddTransactionSheet edit-mode
  reuses the create form's segmented controls and per-member
  rows. A dedicated `[txnId]/edit.tsx` route is *not* shipped;
  edit happens in a sheet from the detail page.

## Coverage

- Backend: 99% floor maintained (final: 99.02%).
- Client: existing `lib/**` 99/95, `app/**` 80/70, `components/**`
  80/70 thresholds maintained.
