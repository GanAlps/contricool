# Phase 3a — Friends Backend — Requirements

## Overview

Phase 3a implements the **friends** feature backend on top of the
Phase 2c authentication surface. After 3a, an authenticated user
(User A) can:

1. Add another user (User B) by exact email
   (`POST /v1/friends/add`).
2. List all of their accepted friends, paginated
   (`GET /v1/friends`).
3. Remove a friendship (`DELETE /v1/friends/{user_id}`).
4. Read a per-friend balance (`GET /v1/friends/{user_id}/balance`)
   that returns 0 / null until Phase 4 wires real transaction
   aggregates.

Phase 3a is **backend only**. The Expo client UI for friends ships
in Phase 3b. The OpenAPI spec + SDK regenerate as part of 3a so 3b
has a typed contract to consume.

## Scope

### In scope (this phase)

- New backend feature module
  `apps/api/app/features/friends/` with `repository.py`,
  `service.py`, `routes.py`, `models.py`, `errors.py`, `README.md`.
- Four endpoints under `/v1/friends/*`, all behind the JWT authorizer.
- DDB friendship rows on the existing `ContriCool-Users-<env>` table
  (no new table, no schema migration; the row shape is already
  reserved in Design 7).
- Per-user rate-limit on `POST /v1/friends/add` — 30/hour. New
  `RATE#FRIEND_ADD#<user_id>` row class on the Users table.
- `make openapi` regenerates `packages/openapi/openapi.yaml` and the
  SDK schema; CI drift check covers the new routes.
- Backend tests (positive + negative; coverage ≥ 99%).
- Updated `app/core/policy.py` adds `is_friend(user_id, other_user_id)`
  helper for use by Phase 4 transactions.

### Out of scope (later phases)

- Frontend friends UI (Phase 3b).
- Pending friend requests / accept-decline flow (deferred per Design 6
  — bilateral acceptance is automatic at MVP).
- Friend invites for not-yet-on-platform users (deferred per Design 6).
- Block / mute (out of scope MVP per Design 6).
- Phone-based friend search (CONSTRAINTS.md — email only at MVP).
- Real balance numbers (Phase 4 — `/balance` returns the fully-typed
  shape with zeros for now so Phase 3b's UI is forward-compatible).

## Functional Requirements

### R1 — Add friend (`POST /v1/friends/add`)

- **R1.1** — Request body: `{email: string}`. Authenticated route
  (JWT authorizer, then `current_principal()` Lambda-side).
- **R1.2** — `email` is normalised: trimmed, lowercased, validated
  with Pydantic `EmailStr`. Whitespace-only or non-email payloads
  → **400** `INVALID_IDENTIFIER` per CLAUDE.md red-line 3
  ("Friend-add via phone identifier — reject 400
  `INVALID_IDENTIFIER` (email-only at MVP)").
- **R1.3** — Email lookup uses GSI1 (`EMAIL#<lookup_hash(email)>` →
  `USER#<user_id>`). The lookup hash function lives in
  `app/core/lookup_hash.py` (Phase 2b).
- **R1.4** — Resolved target user **must not be the requester** —
  self-add → **422** `SELF_ADD_FORBIDDEN`.
- **R1.5** — Friendship is bilateral and canonical-pair:
  - `min_id = min(requester_id, target_id)`
  - `max_id = max(requester_id, target_id)`
  - One DDB row at `PK=USER#<min_id>`, `SK=FRIEND#<max_id>`,
    GSI1 keys `GSI1PK=USER#<max_id>`, `GSI1SK=FRIEND#<min_id>`.
  - Attributes: `created_by` (the requester's user_id),
    `created_at` (ISO-8601).
- **R1.6** — Write uses `TransactWriteItems` (single Put with
  `ConditionExpression="attribute_not_exists(PK)"`) so a duplicate
  add → **409** `CONFLICT`.
- **R1.7** — Per-user rate-limit: 30 add-requests per rolling hour
  per `requester_id`. Counter row at
  `PK=RATE#FRIEND_ADD#<requester_id>`, `SK=COUNTER`, attributes
  `attempts_hour`, `hour_window_started_at`, `ttl=now+24h`. Same
  conditional-update pattern as the OTP rate-limit in
  `app/features/auth/rate_limit.py` — counted **before** the
  Cognito/DDB lookup so unsuccessful attempts (404, 409, 422) all
  count against the cap. Limit hit → **429** `RATE_LIMITED` with
  `Retry-After` header.
- **R1.8** — Response **200** `{ user_id, name, currency, since: <iso8601> }`.
  The response is **the friend's** display name + currency (read
  from the target's `META` row), not the requester's.
- **R1.9** — Error mapping:
  - `INVALID_IDENTIFIER` → 400.
  - `USER_NOT_FOUND` → 404 (no GSI1 hit on the email hash).
  - `SELF_ADD_FORBIDDEN` → 422.
  - `CONFLICT` → 409 (friendship already exists).
  - `RATE_LIMITED` → 429.
  - `VALIDATION_ERROR` → 422 (Pydantic).
  - 5xx → 500 `INTERNAL`.

### R2 — List friends (`GET /v1/friends`)

- **R2.1** — Authenticated. No body.
- **R2.2** — Query params:
  - `limit`: 1..100, default 50.
  - `cursor`: opaque base64url string. Absent → start from beginning.
- **R2.3** — Result is a list of friends sorted by `other_user_id`
  ascending. Each item:
  ```json
  {
    "user_id": "01J...",
    "name": "Alice",
    "currency": "USD",
    "since": "2026-04-29T20:01:45Z"
  }
  ```
- **R2.4** — DDB query path: friendships are stored with the canonical
  pair so every user's friendships are split across:
  - **base view** (`PK=USER#<self>`, `SK begins_with FRIEND#`) — friends
    whose user_id is **larger than** self.
  - **GSI1 view** (`GSI1PK=USER#<self>`, `GSI1SK begins_with FRIEND#`)
    — friends whose user_id is **smaller than** self.
  The service merges both, sorts by `other_user_id`, then slices to
  `limit`.
- **R2.5** — `name` and `currency` come from a `BatchGetItem` over
  the resolved friend IDs' `USER#<id>` `META` rows. Skipping the
  `BatchGetItem` would force the friendship row to duplicate identity
  attributes — rejected: keeps the META row as the single source of
  truth (Phase 2c R2.3).
- **R2.6** — Response **200** body:
  ```json
  {
    "items": [ ... ],
    "next_cursor": "<opaque>" | null
  }
  ```
  `next_cursor` is `null` when there are no more results.
- **R2.7** — The cursor encodes the merged-list position. The
  internal shape is documented in `design.md`; clients must treat
  it as opaque.
- **R2.8** — `name` and `currency` are the **only** identity fields
  in the response. **Email and phone are never included.**

### R3 — Remove friend (`DELETE /v1/friends/{user_id}`)

- **R3.1** — Authenticated. `user_id` path parameter is the friend's
  user_id (not the requester's).
- **R3.2** — Hard delete of the canonical-pair row:
  `DeleteItem` at `PK=USER#<min(a,b)>`, `SK=FRIEND#<max(a,b)>` with
  `ConditionExpression="attribute_exists(PK)"`.
- **R3.3** — On success → **204 No Content**.
- **R3.4** — Friendship not found → **404** `USER_NOT_FOUND` (we
  use the same code as add to keep client error mapping uniform —
  semantically: "no such friendship to delete").
- **R3.5** — Self-delete (`user_id == requester_id`) → **422**
  `SELF_ACTION_FORBIDDEN`.
- **R3.6** — `user_id` malformed (not a ULID) → **422**
  `VALIDATION_ERROR`.
- **R3.7** — No rate-limit on remove at MVP — Cognito + API Gateway
  per-route throttling cover abuse cases.

### R4 — Friend balance (`GET /v1/friends/{user_id}/balance`)

- **R4.1** — Authenticated. `user_id` is the friend's user_id.
- **R4.2** — Requires an active friendship between requester and
  target (not just the target existing as a user). No friendship
  → **404** `USER_NOT_FOUND` (same masking as R3.4).
- **R4.3** — Phase 3a returns a fully-shaped placeholder; Phase 4
  fills in the real numbers.
  ```json
  {
    "user_id": "01J...",
    "currency": "USD",
    "net": "0.00",
    "settlement_status": "settled",
    "last_transaction_at": null
  }
  ```
  - `currency`: requester's currency (read from requester's `META`
    row); per CONSTRAINTS.md a user's transactions all live in their
    own currency at MVP.
  - `net`: string representation of a `Decimal`. Positive = the
    friend owes the requester. Negative = the requester owes the
    friend. Zero = settled.
  - `settlement_status`: enum `{settled, friend_owes, you_owe}`.
    Always `settled` at Phase 3a.
  - `last_transaction_at`: ISO-8601 timestamp or `null`.
- **R4.4** — Self-balance (`user_id == requester_id`) → **422**
  `SELF_ACTION_FORBIDDEN`.

## Non-functional Requirements

### NFR1 — Authorization & policy

- **NFR1.1** — Every endpoint requires a valid JWT (id token, per
  the Phase 2c two-token contract).
- **NFR1.2** — `app/core/policy.py` adds:
  ```python
  def is_friend(user_id: str, other_user_id: str) -> bool:
      """Single source of truth for friend-checks across the codebase."""
  ```
  Uses the same canonical-pair lookup as R3.2. Phase 4
  (transactions) and any future per-friend feature consumes this
  helper rather than re-implementing the lookup.
- **NFR1.3** — Friend lists are private — no endpoint at any level
  reveals **another user's** friends. The only friend-list endpoint
  is `GET /v1/friends` which returns the **caller's** list.

### NFR2 — IAM & DDB grants

- **NFR2.1** — The Lambda execution role (already in `api_stack.py`)
  needs `dynamodb:Query` on the Users table's GSI1 ARN — verify it's
  already granted. If not, add it scoped to `<UsersTableArn>/index/GSI1`.
- **NFR2.2** — `dynamodb:BatchGetItem` on the Users table ARN.
- **NFR2.3** — `dynamodb:TransactWriteItems` on the Users table ARN
  (already needed for Phase 2c verify-email — verify present).
- **NFR2.4** — No `Scan`. No `*` on dynamodb actions. Synth tests
  enforce.

### NFR3 — Rate-limiting & throttling

- **NFR3.1** — App-layer rate-limit on `POST /v1/friends/add`: 30
  adds/hour/requester. Limit row class: `RATE#FRIEND_ADD#<user_id>`.
- **NFR3.2** — API Gateway per-route throttling on
  `POST /v1/friends/add`: burst 5, sustained 1/s (added in
  `api_stack.py` `_ROUTE_THROTTLES`).
- **NFR3.3** — No per-user rate-limit on list / remove / balance —
  the stage-level 5,000 RPS / 10,000 burst covers them.

### NFR4 — Logging & observability

- **NFR4.1** — Auth-store-style redaction stays in force. `email`
  is **logged only as a hash** (the `lookup_hash` value already used
  for the GSI1 key — emit as `email_hash` field). Raw email never
  reaches structured logs.
- **NFR4.2** — Friend-add success log line:
  `{event: "friend_added", requester_id, friend_id, email_hash}`.
- **NFR4.3** — Add-with-INVALID_IDENTIFIER, USER_NOT_FOUND, CONFLICT,
  SELF_ADD_FORBIDDEN all emit one INFO line each — no stack traces
  for expected error paths.

### NFR5 — Test coverage

- **NFR5.1** — 99% coverage on `apps/api/app/features/friends/**`
  per the project floor.
- **NFR5.2** — Tests live in `apps/api/tests/features/friends/`
  mirroring the source layout.
- **NFR5.3** — Reuse the moto + `seeded_user(currency='USD')` fixtures
  from `apps/api/tests/conftest.py`.

### NFR6 — OpenAPI + SDK regen

- **NFR6.1** — `make openapi` regenerates `packages/openapi/openapi.yaml`
  with the four new routes + their request/response schemas.
- **NFR6.2** — `make openapi-check` in CI fails any drift.
- **NFR6.3** — `pnpm --filter @contricool/client-sdk build` regenerates
  `src/schema.d.ts` so 3b can consume typed shapes.

## Negative-test Requirements (Red Line 3)

Every endpoint gets at least one negative per error class. Each
negative is a discrete pytest function in
`apps/api/tests/features/friends/test_<endpoint>.py` (or
`_security.py` for pure-security cases).

### Add-friend negatives

- **N1** — Add with email-shaped phone (e.g. `"+14155552671"`) →
  **400** `INVALID_IDENTIFIER`. (CLAUDE.md red-line 3.)
- **N2** — Add with malformed email → **422** `VALIDATION_ERROR`,
  field=`email`.
- **N3** — Add with missing/empty body → **422**.
- **N4** — Add an email with no matching user → **404** `USER_NOT_FOUND`.
- **N5** — Add an existing friend → **409** `CONFLICT`.
- **N6** — Add yourself (`email` resolves to requester) → **422**
  `SELF_ADD_FORBIDDEN`.
- **N7** — Add with no Authorization header → **401**.
- **N8** — Add with expired/tampered/wrong-pool JWT → **401**
  (regression of Phase 2c N16–N19).
- **N9** — 31st add-request in one hour → **429** `RATE_LIMITED`,
  `Retry-After` ≤ 3600 and > 0.
- **N10** — Email hash of the target leaks into logs only as a
  hash (no raw email in the log line).

### List-friends negatives

- **N11** — `limit > 100` → **422** `VALIDATION_ERROR`.
- **N12** — `limit < 1` → **422**.
- **N13** — Tampered/garbage cursor → **422** `INVALID_CURSOR`.
- **N14** — Cursor from a different user (encrypted/signed cursor
  forgery scenario) → **422**. (Cursor is bound to the requester's
  user_id at issue time so cross-user cursor reuse is rejected.)
- **N15** — `name` / `currency` are the only identity fields in
  list responses; `email` and `phone` are never present
  (test asserts the response model has no such fields).
- **N16** — Unauthenticated GET → **401**.

### Remove-friend negatives

- **N17** — DELETE for a non-friend → **404** `USER_NOT_FOUND`.
- **N18** — DELETE self → **422** `SELF_ACTION_FORBIDDEN`.
- **N19** — DELETE with malformed `user_id` (not a ULID) → **422**.
- **N20** — Unauthenticated → **401**.

### Balance negatives

- **N21** — Balance for a non-friend → **404** `USER_NOT_FOUND`.
- **N22** — Balance for self → **422** `SELF_ACTION_FORBIDDEN`.
- **N23** — Balance for a malformed user_id → **422**.
- **N24** — Unauthenticated → **401**.

### Cross-user privacy negatives (red line 3 — privacy)

- **N25** — User C (not friends with A or B) calls
  `GET /v1/friends/{B_id}/balance` while A is friends with B → **404**
  `USER_NOT_FOUND` (no information leak about whether B exists or
  whether B is friends with anyone).
- **N26** — User C calls `DELETE /v1/friends/{B_id}` while A is
  friends with B → **404** (same).
- **N27** — User C cannot enumerate users by trying random emails:
  rate-limit + USER_NOT_FOUND/CONFLICT only, no "this email exists
  but isn't a user" response.

### Concurrent-add negatives

- **N28** — Two simultaneous `POST /v1/friends/add` calls (User A
  adding B, User B adding A) — only one succeeds, the other returns
  **409** `CONFLICT` deterministically. The transactional
  `attribute_not_exists(PK)` condition guarantees at-most-once write.

### Synth / IAM negatives

- **N29** — Synth: Lambda IAM does **not** contain `dynamodb:Scan`
  on the Users table.
- **N30** — Synth: Lambda IAM does **not** contain `dynamodb:*` on
  any resource.
- **N31** — Synth: API Gateway has a per-route throttle on
  `POST /v1/friends/add`.

## Constraints

- **CLAUDE.md red-line 1** — No hardcoded ARNs, account IDs, table
  names in code. Table name comes from SSM cold-start config (Phase 2b).
- **CLAUDE.md red-line 2** — Per-user rate-limit + per-route API
  Gateway throttling both ship in the same PR. SSM cost is zero
  (parameter store standard tier).
- **CLAUDE.md red-line 3** — N1–N31 above ship with this PR. Coverage
  floor 99% on `friends` feature.
- **Email-only at MVP** — Per CONSTRAINTS.md and Design 4. No
  phone-search, no SMS, no `/v1/friends/add-by-phone`, no `/invite`
  (invite-by-phone-not-on-platform also deferred).
- **No new DDB table** — the existing `ContriCool-Users-<env>` table
  carries friendship rows. No CDK Data-stack change required.
- **Friend lists are private** — no endpoint reveals another user's
  friends.

## Summary

Phase 3a stands up the four-endpoint friends backend on top of the
existing Phase 2 surface, adds the `is_friend` policy helper used by
Phase 4 transactions, regenerates the OpenAPI spec + SDK schema, and
ships per-user + per-route rate-limiting with 31 negative tests
covering identity validation, privacy, race conditions, and IAM
scope. Phase 3b consumes the resulting SDK to build the friends UI.
