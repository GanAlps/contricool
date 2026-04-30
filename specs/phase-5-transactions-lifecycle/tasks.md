# Phase 5 — Tasks (executed in a single PR)

- [x] Backend errors: `ForbiddenError`, `PreconditionFailedError`,
  `GoneError`, `NotDeletedError`.
- [x] Backend repo: `update_transaction`, `soft_delete_transaction`,
  `restore_transaction`, `get_audit_rows`, `hard_delete_transaction`,
  `set_audit_ttl_for_purge`, `scan_soft_deleted`.
- [x] Backend service: `update_transaction`, `delete_transaction`,
  `restore_transaction`, `_meta_to_snapshot`, `_load_for_mutation`.
- [x] Backend routes: `PUT /v1/transactions/{txn_id}`,
  `DELETE /v1/transactions/{txn_id}`,
  `POST /v1/transactions/{txn_id}/restore`.
- [x] Cleanup module + handler entrypoint at `apps/api/app/cleanup/main.py`.
- [x] Backend integration tests (`tests/features/transactions/test_lifecycle.py`):
  29 tests covering R1–R5 + N1–N19 + AUDIT roundup + repo-direct
  race tests for `StaleUpdatedAtError` and `NotFriendError`.
- [x] Cleanup integration tests (`tests/cleanup/test_cleanup.py`):
  5 tests covering R6 + the three repo helpers + handler entry.
- [x] CDK: extend `transactions_table.grant` with `DeleteItem` (edit
  drops member rows). `Scan` + `BatchWriteItem` deliberately *not*
  granted to the API Lambda — the future cleanup Lambda gets its
  own scoped role.
- [x] Frontend hooks: `useUpdateTransaction`, `useDeleteTransaction`,
  `useRestoreTransaction`. Cache-invalidation across
  `transactions[*]`, the per-txn key, and per-member balance keys.
- [x] Frontend `AddTransactionSheet`: `existing?: Transaction` prop.
  Edit-mode hydrates fields, PUTs with `If-Match`, surfaces 412 +
  403 banners. Open-effect identity-deduped on `existingId` so
  in-flight typing isn't wiped by a parent re-render.
- [x] Frontend detail page: edit + delete buttons gated on
  `creator_id === me.user_id`. Confirm-delete sheet. Restore bar
  shown when `deleted_at` is set; tapping `Restore` calls the hook
  and surfaces `GONE` as a 30-day-expired toast.
- [x] OpenAPI regenerated; SDK schema regenerated; drift gate clean.
- [x] Lint + typecheck clean (ruff, mypy --strict, biome, tsc).
- [x] Coverage: backend 99.02%; client thresholds met.

## Deferred to follow-up

- CDK wire-up of the cleanup Lambda (separate construct, EventBridge
  cron, scoped IAM). Cleanup module + tests are in place; only the
  scheduling is missing.
- Optimistic-delete with toast-based undo (currently a confirm sheet
  is used; design.md noted a toast-based undo as the eventual UX).
