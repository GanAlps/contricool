# Phase 4b — Transactions Backend Feature — Requirements

## Overview

Phase 4b builds the **`transactions` backend feature** on the
`ContriCool-Transactions-<env>` table delivered in Phase 4a. After this
phase merges and deploys, three mutually-friended users can create,
list, get, and pair-compute transactions through `/v1/transactions/*` and
the existing `/v1/friends/{id}/balance` route — but cannot yet edit,
delete, or restore (Phase 5).

This phase realises the **EXECUTION_PLAN.md sub-section 4b** scope and
draws its semantics from **Designs 5 (auth/policy), 6 (transaction
domain), 7 (data model), 8 (API), and 13 (privacy)**.

## Requirements

### R1 — Create transaction (`POST /v1/transactions`)

A creator can create a transaction with:

- **`name`** (1..120 unicode chars, trimmed; required).
- **`type`** = `expense` | `settlement`.
- **`amount`** (positive `Decimal`, 2 decimal places, max 12 digits).
- **`currency`** = `USD` | `INR` (must match every member's currency).
- **`txn_date`** (ISO date; default = today UTC; reject > +1 day or > 10
  years past).
- **`note`** (0..500 chars; optional).
- **`split_method`** = `equal` | `amount` | `share` | `percent`.
- **`members`** = list of `{ user_id, share?, percent?, owed_amount? }`,
  2..10 entries; **must include the creator**; every other member must
  be a current friend; no duplicates.
- **`payers`** = list of `{ user_id, paid_amount }`, 1..10 entries; every
  payer must be a member; payer `user_id`s unique; sum of `paid_amount`
  must equal `amount`.
- **`Idempotency-Key`** request header (UUID v4 shape; required).

The server:

1. Validates the body (Pydantic) and the per-method invariants:
   - `equal` → no per-member input expected.
   - `amount` → every member has `owed_amount`; sum equals `amount`.
   - `share` → every member has `share` > 0.
   - `percent` → every member has `percent` > 0; sum equals `100.00`
     within ±0.01 tolerance.
   - `settlement` → exactly 2 members, exactly 1 payer,
     `split_method = amount`, the non-payer's `owed_amount = amount`,
     payer's `owed_amount = 0`.
2. Rejects negative or zero `amount`.
3. Rejects `txn_date` > today + 1 day or older than 10 years.
4. Computes server-side `owed_amount` for `equal`/`share`/`percent`,
   applying half-up rounding to 2 decimals; the **last member in the
   sorted member list** absorbs any rounding remainder so
   `sum(owed_amount) == amount` exactly.
5. Verifies (via DDB `ConditionCheck`) that every other member is a
   current friend of the creator.
6. Verifies (via DDB `GetItem` per non-creator, batched) that every
   member's `currency == request.currency`. If any member's currency
   differs → 422 `CURRENCY_MISMATCH`.
7. Writes via a **single `TransactWriteItems`** spanning Users
   (`ConditionCheck` per friendship) + Transactions (META + N MEMBER
   rows + AUDIT row + IDEMPOTENCY row).
8. Returns 201 with the persisted transaction shape (META fields +
   server-computed `owed_amount` per member + `created_at`,
   `updated_at`).

If the same idempotency key is replayed by the same user **with the
same body hash**, the cached 201 response is returned (status code,
response body, headers). Replay with a different body hash → 409
`IDEMPOTENCY_KEY_REUSED`. Different user same key → distinct response
(keyed by `<user_id>#<key>`).

### R2 — Get transaction (`GET /v1/transactions/{txn_id}`)

A member can read a single non-deleted transaction:

- 200 with full META + members + computed payer/owed amounts.
- 404 `NOT_FOUND` if the transaction doesn't exist OR the requester
  isn't a member (mask the difference; CLAUDE.md red-line 3 entry
  "wrong-user authorization").
- 404 `NOT_FOUND` if `deleted_at` is set (Phase 5 will widen this for
  creator-only restore reads).

### R3 — List my transactions (`GET /v1/transactions`)

Paginated list of the requester's transactions, newest first:

- Optional `friend_id` query param → restricts to transactions where
  both the requester and `friend_id` are members (Pattern #9 from
  Design 7: two GSI1 queries + intersection).
- `limit` 1..100, default 20.
- Cursor-based pagination via opaque, requester-bound HMAC cursor (mirror
  the friends-feature cursor module).
- Returns each transaction's META + the requester's `owed_amount` for
  rendering "you owe / you're owed" rows.
- Soft-deleted transactions never returned (Phase 5 widens for creator
  restore).

### R4 — Friend balance (`GET /v1/friends/{user_id}/balance`)

The Phase 3a placeholder route now returns the **real** net balance:

- 200 with `{ user_id, currency, net, settlement_status,
  last_transaction_at }`.
- `net` is from the requester's perspective: positive = friend owes
  requester; negative = requester owes friend.
- `settlement_status` ∈ { `settled`, `friend_owes`, `you_owe` }
  derived from `net` (`settled` iff `abs(net) < 0.01`).
- Computed by `balance.compute_pair_balance(...)` — pure function over
  the intersection of `Pattern #8` queries for the requester and the
  friend.
- 404 if not friends (existing behaviour).

### R5 — Member cap, payer cap, idempotency window

| Constraint | Value | Source |
|---|---|---|
| Min members | 2 | Design 6 |
| Max members | 10 | Design 6 / 7 |
| Payer cap | min(members count, 10) | Design 6 |
| Currency set | { USD, INR } | Design 6 |
| Idempotency TTL | 24 h | Design 7 |
| `txn_date` past horizon | 10 years | Design 6 |
| `txn_date` future tolerance | +1 day | Design 6 |

### R6 — IAM grants (CDK ApiStack)

The Lambda's IAM policy grows the following actions, all enumerated
(no wildcards):

- **On Users table**: keep the Phase 3a set
  (`GetItem`/`PutItem`/`UpdateItem`/`Query`/`BatchGetItem`/`DeleteItem`).
  **Add `ConditionCheckItem`** — required by `TransactWriteItems` to
  reference friendship rows from the cross-table transact.
- **On Transactions table**: add the same `GetItem`/`PutItem`/
  `UpdateItem`/`Query`/`BatchGetItem`/`ConditionCheckItem` set, plus
  **`TransactWriteItems`**.

Forbidden everywhere (must remain absent):

- `dynamodb:*` (wildcard).
- `dynamodb:Scan`.
- `dynamodb:BatchWriteItem`.
- `dynamodb:DeleteItem` on the Transactions table (soft-delete uses
  `UpdateItem`; hard-delete is a Phase 6 cleanup-job concern).

### R7 — Lambda env + SSM

- New SSM parameter consumed at cold start:
  `/contricool/<env>/ddb/transactions-table-name`.
- New `AppConfig.transactions_table_name` field; routed through the same
  `_PARAMETER_KEYS` batch.
- New Lambda env var `TRANSACTIONS_TABLE_NAME` set by `ApiStack` for
  Powertools idempotency persistence.
- The deploy workflow's existing "write DDB outputs to SSM" step is
  extended to write the Phase 4a-emitted CfnOutput
  `TransactionsTableName`. CI gates the deploy until this writes
  successfully.

### R8 — Powertools idempotency

`POST /v1/transactions` is decorated with the Powertools
`@idempotent_function` decorator backed by
`DynamoDBPersistenceLayer(table_name=<transactions_table>)`:

- Persistence row layout: `PK = "IDEMPOTENCY#<user_id>#<key>"`,
  `SK = "META"` (matches Design 7).
- TTL attribute `ttl` (24-hour expiry, attribute name compatible with the
  table's TTL config).
- The `event_key_jmespath` derives the cache key from
  `(user_id, idempotency_key)`; the request body hash is the *payload
  validation hash* (different body with same key → 409).
- Idempotency cache write happens inside the same `TransactWriteItems`
  as the META + MEMBER rows when the create succeeds (atomicity); we
  use the Powertools "register lambda context" hook to defer the
  persistence write to our repository so we can include it in the
  transact. **Open trade-off** — see design.md.
- On successful idempotent replay, the cached response is served at
  the same status code (201), with `Idempotency-Replayed: true`
  response header.

### R9 — Tests

**Coverage floor: 99%** per CLAUDE.md global guideline. New tests live
in `apps/api/tests/features/transactions/`, mirroring the source folder.

Required test classes (positive):

- Create: each split method × happy-path member counts.
- Equal split: rounding remainder absorbed by last member.
- Hypothesis property test: for every `(amount, members,
  split_method, args)` valid input, `sum(owed_amount) == amount`.
- Multi-payer create: balances proportionally split.
- Get / list / list-with-friend / pagination / cursor encode-decode.
- Friend balance: real numbers across a series of transactions.
- Idempotent replay: same user + same key + same body → identical 201
  response (no second write).

Required negative tests (every entry must exist):

- Non-friend member → 422 `NOT_FRIEND`.
- Self not in members → 422 `SELF_NOT_MEMBER`.
- 1-member list → 422 `MIN_MEMBERS`.
- 11-member list → 422 `MAX_MEMBERS`.
- Currency mismatch (member's currency ≠ txn currency) → 422
  `CURRENCY_MISMATCH`.
- `percent` summing to 99.0 → 422 `PERCENT_SUM`.
- `amount` split with owed-sum ≠ amount → 422 `OWED_SUM`.
- Payer not in members → 422 `PAYER_NOT_MEMBER`.
- Paid-sum ≠ amount → 422 `PAID_SUM`.
- Negative or zero `amount` → 422 `INVALID_AMOUNT`.
- `txn_date` 1 year in the future → 422 `INVALID_DATE`.
- Get as non-member → 404 `NOT_FOUND` (mask).
- List my-transactions never returns transactions I'm not in.
- List with-friend-X never returns transactions X is not in.
- Idempotency-key collision across users → both succeed.
- POST without `Idempotency-Key` → 400 `IDEMPOTENCY_KEY_REQUIRED`.
- Concurrent friendship-removal (delete a friendship, then try to
  create a transaction with that ex-friend) → 422 `NOT_FRIEND` via
  the friendship `ConditionCheck` failing.
- All standard auth negatives via the existing JWT helpers (no JWT,
  expired, tampered, wrong-pool, wrong-aud) — at minimum one per
  route.
- Soft-deleted transaction (seed `deleted_at`) → 404 on `GET` and
  absent from list (Phase 5 will widen).

### R10 — Observability

- Structured Powertools log lines on every create (
  `txn_created`, `txn_create_not_friend`, `txn_create_currency_mismatch`,
  `txn_create_idempotency_replay`).
- **Never log**: raw email, raw amount-only-without-context, the
  body hash, or the idempotency key in plaintext (use last-8 chars for
  trace correlation).
- Custom EMF metric `TransactionsCreated` (count) and
  `TransactionsTransactWriteFailed` (count) — the Phase 6 dashboard
  consumes these.

### R11 — OpenAPI + SDK regen

- After the feature lands, `make openapi` regenerates
  `packages/openapi/openapi.yaml` and
  `packages/client-sdk/src/schema.d.ts`.
- CI's `openapi-check` job blocks the PR merge if the artifact is
  stale.
- The generated TS SDK is what Phase 4c will import.

### R12 — Out of scope (forward links)

- Edit (`PUT /v1/transactions/{id}`) → Phase 5.
- Soft-delete + restore → Phase 5.
- Audit-row read endpoint → Phase 5.
- Frontend transaction UI (dashboard, list, new-txn form) → Phase 4c.
- Audit-row Stream consumer → Phase 6.
- Per-user balance materialized view → post-MVP.

## Edge cases

- **Rounding-remainder predictability**: Hypothesis property test must
  cover `amount = 0.01 / m` for `m ∈ [2, 10]` so the remainder
  algorithm stays deterministic across method choices.
- **`TransactWriteItems` partial failure mapping**: a failed
  friendship `ConditionCheck` returns
  `TransactionCanceledException` with per-item
  `CancellationReasons`. The repository must inspect the reason list
  and surface the right 422 (`NOT_FRIEND`) versus a generic 500.
- **Cross-pool idempotency-key collision**: the persistence row's PK
  is namespaced by `user_id`; two users sending the same
  `Idempotency-Key` value MUST both succeed with independent rows.
- **Currency change race**: if a member changes their currency between
  the validation read and the transact write, the transact still
  commits. We accept this race for MVP (Design 6: currency is
  immutable post-signup at MVP, so the race window is empty in
  practice).
- **Friend-removal between validate and transact**: the
  `ConditionCheck` on the friendship row is what catches this — the
  read-then-validate is advisory; the transact's condition is
  authoritative.

## Summary

Phase 4b delivers the create / get / list / balance backend for
transactions. Splits are pure-function + Hypothesis-tested; the create
path uses a single cross-table `TransactWriteItems`; idempotency is
Powertools-backed; all required negative tests ship with the same PR.
After merge: dev + prod can serve `/v1/transactions/*` end-to-end and
`/v1/friends/{id}/balance` returns real numbers. The frontend
(Phase 4c) consumes the regenerated TS SDK.
