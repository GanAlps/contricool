# `transactions` feature

Backend implementation of the transaction domain (Designs **5, 6, 7, 8**).
Phase **4b** delivers the create / get / list / balance routes.
Phase 5 will add edit / delete / restore / audit-read.

## What this feature does

- Three users who are mutual friends can create expense or settlement
  transactions, listing each user's owed amount.
- Members can read individual transactions, list their own transactions
  (optionally filtered to a specific friend via `friend_id` query param),
  and read pair balances via `/v1/friends/{user_id}/balance`.
- Idempotent on `(user_id, Idempotency-Key)` — a replayed POST returns
  the cached 201 response; a same-key replay with a different body is
  rejected with 409 `IDEMPOTENCY_KEY_REUSED`.
- All cross-table writes (create) are atomic via DDB
  `TransactWriteItems` spanning `ContriCool-Users-<env>` (friendship
  ConditionChecks) and `ContriCool-Transactions-<env>` (META + N
  MEMBERs + AUDIT + IDEMPOTENCY rows).

## API endpoints

| Method | Path | Purpose | Auth | Idempotent? |
|---|---|---|---|---|
| `POST` | `/v1/transactions` | Create transaction. `Idempotency-Key` header required. | JWT | yes |
| `GET` | `/v1/transactions` | List my transactions, newest first. Optional `friend_id` query param to intersect. Pagination via `cursor` + `limit` (1..100, default 20). | JWT | n/a |
| `GET` | `/v1/transactions/{txn_id}` | Get one transaction. 404 `NOT_FOUND` if you're not a member (mask). | JWT | n/a |
| `GET` | `/v1/friends/{user_id}/balance` | (friends route, transactions math) Net balance with a friend across all non-deleted transactions. | JWT | n/a |
| `POST` | `/v1/transactions/{txn_id}/comments` | Member-only: post a free-form comment (1..1000 chars). | JWT | n/a |
| `GET` | `/v1/transactions/{txn_id}/comments` | Member-only: list comments oldest-first. Includes server-generated **system** comments emitted whenever a transaction is edited (kind: `system`, author: `system`). | JWT | n/a |

`TransactionListItem` carries both `my_owed_amount` and
`my_paid_amount` so the dashboard summary can compute
`net = paid - owed` per row without an extra read on `meta.payers`.

System comments are best-effort: a transient DDB write failure on the
COMMENT row is logged but does not roll back a successful META edit,
so the user always sees their edit succeed. The summary is suppressed
for no-op edits.

### Request shapes

`POST /v1/transactions`:

```jsonc
{
  "name": "Dinner at Joe's",      // 1..120 chars
  "type": "expense",                // "expense" | "settlement"
  "amount": "30.00",                // positive Decimal, 2 decimal places
  "currency": "USD",                // "USD" | "INR"
  "txn_date": "2026-04-29",         // ISO date; ≤ today + 1 day; ≥ today − 10 years
  "note": "",                       // 0..500 chars
  "split_method": "equal",          // "equal" | "amount" | "share" | "percent"
  "members": [
    { "user_id": "01H...", "share": null, "percent": null, "owed_amount": null }
    // 2..10 entries; creator must be one of them.
  ],
  "payers": [
    { "user_id": "01H...", "paid_amount": "30.00" }
    // 1..10 entries; subset of members; sum(paid_amount) == amount.
  ]
}
```

Headers:
- `Authorization: Bearer <id-token>` — JWT from Cognito.
- `Idempotency-Key: <opaque>` — required, 1..128 chars, `[A-Za-z0-9._:\-]`.

### Response shapes

`POST /v1/transactions` 201 + `GET /v1/transactions/{id}` 200:

```jsonc
{
  "txn_id": "01K...",
  "creator_id": "01H...",
  "name": "Dinner at Joe's",
  "type": "expense",
  "amount": "30.00",
  "currency": "USD",
  "txn_date": "2026-04-29",
  "note": "",
  "split_method": "equal",
  "members": [
    { "user_id": "01H...", "owed_amount": "10.00", "share": null, "percent": null }
  ],
  "payers": [
    { "user_id": "01H...", "paid_amount": "30.00" }
  ],
  "created_at": "2026-04-29T20:00:00Z",
  "updated_at": "2026-04-29T20:00:00Z",
  "deleted_at": null
}
```

`GET /v1/transactions` 200:

```jsonc
{
  "items": [
    {
      "txn_id": "01K...",
      "name": "Dinner at Joe's",
      "type": "expense",
      "amount": "30.00",
      "currency": "USD",
      "txn_date": "2026-04-29",
      "split_method": "equal",
      "creator_id": "01H...",
      "my_owed_amount": "10.00",
      "created_at": "2026-04-29T20:00:00Z"
    }
  ],
  "next_cursor": null
}
```

### Error codes

Stable codes (returned in `error.code`):

| Code | HTTP | Cause |
|---|---|---|
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | `POST` missing the `Idempotency-Key` header. |
| `NOT_FOUND` | 404 | Unknown txn or non-member request. |
| `IDEMPOTENCY_KEY_REUSED` | 409 | Same key + different body. |
| `NOT_FRIEND` | 422 | A non-creator member is not a friend. |
| `CURRENCY_MISMATCH` | 422 | A member's currency ≠ txn currency. |
| `SELF_NOT_MEMBER` | 422 | Creator not in `members`. |
| `MIN_MEMBERS` | 422 | Fewer than 2 members. |
| `MAX_MEMBERS` | 422 | More than 10 members (Pydantic-level). |
| `SETTLEMENT_SHAPE` | 422 | Settlement with ≠ 2 members. |
| `PAYER_NOT_MEMBER` | 422 | Payer not in `members`. |
| `PAID_SUM` | 422 | `sum(paid_amount) ≠ amount`. |
| `OWED_SUM` | 422 | `amount`-method `sum(owed_amount) ≠ amount`. |
| `PERCENT_SUM` | 422 | `percent`-method sum not in `100 ± 0.01`. |
| `INVALID_AMOUNT` | 422 | Non-positive amount. |
| `INVALID_DATE` | 422 | Date out of accepted window. |
| `INVALID_CURSOR` | 422 | Cursor tampered, expired, or cross-user. |
| `VALIDATION_ERROR` | 422 | Generic structural/Pydantic validation failure. |

## Configuration

| Env var / SSM param | Source | Used for |
|---|---|---|
| `ENV_NAME` | Lambda env | Per-env routing of SSM names. |
| `AWS_REGION` | Lambda env | DDB / SSM region. |
| `TRANSACTIONS_TABLE_NAME` | Lambda env (set by `ApiStack`) | Cold-start DDB table reference. |
| `/contricool/<env>/ddb/transactions-table-name` | SSM | Authoritative table name read into `AppConfig.transactions_table_name`. |
| `/contricool/<env>/pii-salt` | SSM SecureString | HMAC key for the cursor module (re-uses friends-feature salt). |

## Component layout

```
features/transactions/
  __init__.py
  balance.py       # pure-function pair-balance compute
  errors.py        # typed AuthError subclasses
  models.py        # Pydantic v2 schemas
  README.md        # this file
  repository.py    # DDB ops including TransactWriteItems
  routes.py        # FastAPI router
  service.py       # business logic + idempotency
  splits.py        # equal/amount/share/percent algorithms
```

## Known limitations

- Edit / delete / restore endpoints are **deferred to Phase 5**.
- Audit-row read endpoint is **deferred to Phase 5**; rows are written
  on every create but not yet queryable.
- Member cap is **10** (Design 6); raising is a one-line
  `MAX_MEMBERS` change and a Pydantic-field bump post-MVP.
- Currencies fixed to **USD / INR** at MVP.
- Soft-delete + 30-day restore window are wired in the data model
  (META has `deleted_at`) but not exposed to writers yet.
- Pair balance is computed on read (no materialized view); fine at
  MVP volume (<5k transactions per active user). Re-evaluate
  post-launch if balance reads slow.

## How to use the feature locally

End-to-end smoke (dev cluster):

```bash
# 1. Sign up and verify two test accounts via /v1/auth/* (Phase 2c).
# 2. As user A, add user B as friend (Phase 3a).
# 3. Create the transaction:
curl -X POST https://<dev-cf-domain>/v1/transactions \
  -H "Authorization: Bearer <id-token>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Dinner",
    "type": "expense",
    "amount": "30.00",
    "currency": "USD",
    "txn_date": "2026-04-29",
    "split_method": "equal",
    "members": [{"user_id": "<A-ULID>"}, {"user_id": "<B-ULID>"}],
    "payers":  [{"user_id": "<A-ULID>", "paid_amount": "30.00"}]
  }'

# 4. As B, read the balance:
curl https://<dev-cf-domain>/v1/friends/<A-ULID>/balance \
  -H "Authorization: Bearer <B-id-token>"
# {"net":"-15.00","settlement_status":"you_owe", ...}
```

Tests:

```bash
cd apps/api && /home/oshogupta/workspace/master-venv/bin/pytest tests/features/transactions/ -q
```

Coverage gate (per CLAUDE.md):

```bash
/home/oshogupta/workspace/master-venv/bin/pytest tests/ \
  --cov=app --cov-fail-under=99
```
