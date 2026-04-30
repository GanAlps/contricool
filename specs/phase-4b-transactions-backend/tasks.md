# Phase 4b — Transactions Backend Feature — Tasks

Tasks are grouped into the four implementation strata; each stratum
ends with its own tests passing before the next stratum begins.

## Stratum 1 — CDK + config + scaffolding

### T1 — `ApiStack` accepts `transactions_table` + grants IAM

- File: `apps/infra/stacks/api_stack.py`
- New required kwarg `transactions_table: dynamodb.ITable`.
- Add `dynamodb:ConditionCheckItem` to the existing Users grant.
- Add a grant on `transactions_table` with `GetItem`, `PutItem`,
  `UpdateItem`, `Query`, `BatchGetItem`, `ConditionCheckItem`,
  `TransactWriteItems`. **No** `DeleteItem` (soft-delete is `UpdateItem`).
- Set the Lambda env var `TRANSACTIONS_TABLE_NAME = transactions_table.table_name`.

### T2 — `app.py` wires the new table

- Pass `transactions_table=data.transactions_table` to `ApiStack(...)`.

### T3 — Synth tests evolve

- File: `apps/infra/tests/test_synth.py`
- `test_api_stack_lambda_iam_ddb_actions_enumerated` now asserts the
  union (Phase 2c+3a Users actions + Phase 4b additions on Transactions).
  Forbidden: `dynamodb:*` wildcard, `dynamodb:Scan`,
  `dynamodb:BatchWriteItem`. (`TransactWriteItems` and
  `ConditionCheckItem` move from forbidden → required.)
- New test: Lambda env var contains `TRANSACTIONS_TABLE_NAME`.
- `_api_stack_auth_data_kwargs` in test_synth.py adds
  `transactions_table=data.transactions_table` so existing tests
  still synth.
- All 70+ existing synth tests stay green.

### T4 — `app.core.config` adds `transactions_table_name`

- File: `apps/api/app/core/config.py`
- Add `transactions_table_name: str` to `AppConfig`.
- Add `/contricool/{env}/ddb/transactions-table-name` to
  `_PARAMETER_KEYS`.

### T5 — Tests for `app.core.config` cover the new field

- File: `apps/api/tests/core/test_config.py` (existing)
- The added field is part of the `AppConfig` shape; existing tests
  that build a fixture `AppConfig` need the new field too.
- Update `apps/api/tests/conftest.py` `_DEFAULT_TEST_CONFIG` likewise.
- Update friends-feature `conftest.py` `cfg` likewise.

### T6 — Run infra + api tests after stratum 1

- `cd apps/infra && pytest tests/ -q` green.
- `cd apps/api   && pytest tests/ -q` green.

## Stratum 2 — Pure-function core (no DDB)

### T7 — `splits.py` with all four methods

- File: `apps/api/app/features/transactions/splits.py`
- Pure functions: `compute_owed_amounts(method, amount, members) -> list[Decimal]`.
- Last-member-absorbs-remainder algorithm; deterministic.
- `Decimal` arithmetic only; `ROUND_HALF_UP` to 2 places.

### T8 — Unit tests for `splits.py`

- File: `apps/api/tests/features/transactions/test_splits.py`
- Per-method happy paths (2-, 3-, 5-member groups).
- Equal split with rounding remainder.
- Settlement special case.

### T9 — Hypothesis property tests

- File: `apps/api/tests/features/transactions/test_splits_property.py`
- Strategy: `(amount, member_count, method, args)` random valid input.
- Property: `sum(compute_owed_amounts(...)) == amount` exactly
  (no `±0.01` slop).
- Property: every emitted value is non-negative `Decimal` with 2 places.
- Add `hypothesis` to `apps/api/pyproject.toml` if not already there.

### T10 — `balance.py` with `compute_pair_balance`

- File: `apps/api/app/features/transactions/balance.py`
- Pure function; takes a list of `(meta, members)` pairs and the two
  user_ids; emits `(net_decimal, settlement_status)`.

### T11 — Unit tests for `balance.py`

- File: `apps/api/tests/features/transactions/test_balance_unit.py`
- Settled case (zero balance after a chain of equal-split + settle).
- One-sided debt; multi-payer scenario; signed-direction sanity.

### T12 — `models.py` with all Pydantic v2 schemas + `model_validator`

- File: `apps/api/app/features/transactions/models.py`
- `MemberInput`, `PayerInput`, `CreateTransactionRequest`,
  `Member`, `Payer`, `Transaction`, `ListTransactionsQuery`,
  `ListTransactionsResponse`, `IdempotencyReplayHeader`.
- Validators raising the dedicated 422-mapped errors (in `errors.py`).

### T13 — Unit tests for `models.py`

- File: `apps/api/tests/features/transactions/test_models.py`
- Each per-method invariant rejection.
- Date-bound rejection.
- Self-not-in-members rejection (depends on routes injecting
  `requester_id`; the validator may be route-level if Pydantic
  doesn't have access — in which case the test moves to
  `test_create_negative.py`).

### T14 — `errors.py` per-feature error classes

- File: `apps/api/app/features/transactions/errors.py`
- `NotFoundError`, `NotFriendError`, `CurrencyMismatchError`,
  `IdempotencyKeyRequiredError`, `IdempotencyKeyReusedError`,
  `SelfNotMemberError`, `MemberCountError`, `ValidationFailedError`,
  `PayerNotMemberError`, `PaidSumError`, `OwedSumError`, `PercentSumError`,
  `InvalidAmountError`, `InvalidDateError`, `InvalidCursorError`.
- Each subclasses `app.features.auth.errors.AuthError` for the shared
  envelope.

### T15 — Unit tests for `errors.py`

- File: `apps/api/tests/features/transactions/test_errors.py`
- Each error has the expected `(http_status, code)` mapping.

### T16 — `cursor.py` HMAC pagination cursor

- File: `apps/api/app/features/transactions/cursor.py`
- Mirror `friends/cursor.py` shape; encode/decode
  `(requester_id, txn_id, expires_at)`.

### T17 — Unit tests for `cursor.py`

- File: `apps/api/tests/features/transactions/test_cursor.py`
- Round-trip; tampered cursor → InvalidCursorError; cross-user
  cursor rejected; expired cursor rejected.

## Stratum 3 — DDB layer

### T18 — `repository.py` — base ops

- File: `apps/api/app/features/transactions/repository.py`
- Module-scope DDB resource + table refs (Users + Transactions).
- `_set_tables_for_tests` injection hook.
- `get_meta(txn_id)`, `get_members(txn_id)`, `query_user_member_rows`
  (Pattern #8 / #9), `batch_get_metas`, `get_idempotency_record`.

### T19 — `repository.create_transaction` — TransactWriteItems

- Build the multi-table transact: N ConditionChecks on Users
  friendship rows + META Put + N MEMBER Puts + AUDIT Put +
  IDEMPOTENCY Put with `attribute_not_exists(PK)`.
- Decode `TransactionCanceledException` per item; surface
  `NotFriendError` when a friendship slot fails.
- On the IDEMPOTENCY-slot conflict, fetch the existing record and
  return its cached response.

### T20 — Repository tests with moto

- File: `apps/api/tests/features/transactions/test_repository.py`
- Happy-path create.
- Friendship missing → `NotFriendError`.
- Idempotency conflict → cached response surfaced.
- Concurrent friendship-removal race → `NotFriendError` (delete
  friendship row mid-flight via moto then retry transact).

## Stratum 4 — Service + routes + integration

### T21 — `service.py`

- `create(requester_id, body, idempotency_key) -> Transaction`.
- `get(requester_id, txn_id) -> Transaction`.
- `list_mine(requester_id, *, limit, cursor, friend_id=None)`.
- `compute_balance(requester_id, friend_id) -> FriendBalanceResponse`.

### T22 — Route handlers

- File: `apps/api/app/features/transactions/routes.py`
- `POST /v1/transactions` — pulls `Idempotency-Key` header, 400 if
  missing.
- `GET /v1/transactions` — accepts `friend_id`, `limit`, `cursor`.
- `GET /v1/transactions/{id}` — ULID validation + 404 mask.
- `GET /v1/friends/{user_id}/balance` is in `friends/routes.py` —
  edit `friends/service.get_balance` to delegate to
  `transactions.service.compute_balance`.

### T23 — Wire router in `main.py`

- File: `apps/api/app/main.py`
- `from app.features.transactions import routes as transactions_routes`
- `api.include_router(transactions_routes.router, prefix="/v1")`

### T24 — Conftest for transactions tests

- File: `apps/api/tests/features/transactions/conftest.py`
- Spin up moto cognito + ddb with **both** Users and Transactions tables.
- Helpers: `seed_user`, `seed_friendship`, `seed_transaction`,
  `mint_id_token(user_id)`, `auth_headers(user_id)`.

### T25 — Integration tests — happy paths

- File: `apps/api/tests/features/transactions/test_create.py`
- Each split-method create returns 201 with computed `owed_amount`s.
- DDB rows match expected layout (META + N MEMBERs + AUDIT +
  IDEMPOTENCY).

### T26 — Integration tests — negative paths

- File: `apps/api/tests/features/transactions/test_create_negative.py`
- All entries in R9's negative-tests list.

### T27 — Get / list / list-with-friend integration tests

- Files: `test_get.py`, `test_list.py`, `test_list_with_friend.py`
- 404 mask, pagination, cursor, intersection, soft-delete absent.

### T28 — Idempotency tests

- File: `test_idempotency.py`
- Same key + same body → cached response.
- Same key + different body → 409.
- Different user same key → independent successes.
- Missing header → 400.

### T29 — Balance tests

- File: `test_balance.py`
- Real numbers across a chain; `settled` after settlement; cross-
  currency friend → 404 (no shared transactions possible per R1).

### T30 — Auth-negative tests for every route

- File: `test_security.py`
- Reuse `_jwt_helpers` for missing / expired / tampered / wrong-pool
  / wrong-aud per route.

### T31 — Coverage check

- `cd apps/api && /home/oshogupta/workspace/master-venv/bin/pytest
  tests/features/transactions/ --cov=app.features.transactions
  --cov-fail-under=99` green.

### T32 — Friends balance test updated

- File: `apps/api/tests/features/friends/test_balance.py`
- The Phase 3a placeholder zero-balance test is replaced by tests
  that seed transactions and assert real balances. (No regression on
  the no-transactions case → `settled`, `net=0`, `last_transaction_at=None`.)

## Stratum 5 — Polish

### T33 — Feature `README.md`

- File: `apps/api/app/features/transactions/README.md`
- What the feature does, route table, env vars, known limits.

### T34 — `make openapi` regen

- Run `make openapi` from repo root; commit the regenerated
  `packages/openapi/openapi.yaml` and
  `packages/client-sdk/src/schema.d.ts`.

### T35 — Update `EXECUTION_PLAN.md`

- Mark Phase 4b done in the sub-phase rollout table once the PR is open.

### T36 — Open PR `feat/phase-4b-transactions-backend`

- Branch off `main`.
- Conventional Commit on the squash:
  `feat(transactions): Phase 4b — backend (splits/balance/CRUD/idempotency)`.
- PR body links the spec folder.
- Wait for CI green (lint, test with 99% cov gate, cdk-diff,
  openapi-check, gitleaks).

## Out of scope for 4b (forward links)

- Edit/delete/restore/audit-read endpoints → Phase 5.
- Frontend transaction UI → Phase 4c.
- Audit-row Stream consumer → Phase 6.
