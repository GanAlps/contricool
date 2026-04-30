# Phase 7b — Tasks

Ordered by dependency. Each phase ends with a green test run for
all code in that phase.

## Phase A — Backend bugfixes (items 4 + 6 + 1 + 2 — small, no schema/wire churn beyond list field)

A1. **Map password-reuse on reset to PASSWORD_REUSED.**
    Add `PASSWORD_REUSED` (422) to auth errors. In
    `cognito_client._map_error`, on `path=="reset_password"` +
    `code=="InvalidParameterException"` whose message mentions
    "different"/"differ"/"previous", return PASSWORD_REUSED.
    Otherwise on the same path, return INVALID_PASSWORD instead of
    the wrong ALREADY_CONFIRMED. Tests: positive + negative for
    both paths.

A2. **Add `my_paid_amount` to `TransactionListItem`.**
    Update Pydantic model and `service.list_transactions` to compute
    from `meta.payers`. Tests: list response carries the right
    value across creator-paid, friend-paid, and split-payer cases.

A3. **`PATCH /v1/me/profile`** — name update.
    - New model `UpdateProfileRequest{name}`, response `MeProfileSlim`
      `{user_id, name, currency}`.
    - Repo `update_user_name(user_id, name)` (conditional on
      attribute_exists + status == "active").
    - Route + service.
    - Tests: positive, blank-name 422, deactivated 403, JWT-missing
      401, currency-not-mutable (no field accepted), idempotent
      same-name 200.

A4. **Block friend removal on non-zero balance.**
    - `BalanceNotSettledError` in friends.errors (409).
    - In `service.remove_friend`, after self-check + before
      `delete_friendship`, call `txn_service.compute_pair_balance`
      and raise `BalanceNotSettledError` if not settled.
    - Tests: positive (settled removes), negative (you-owe blocks,
      friend-owes blocks), self-remove still 422, no-friendship
      still 404.

A5. **Coverage gate.** Run `pytest --cov=app tests/ --cov-fail-under=99`
    for affected modules. Fix any gaps.

## Phase B — Backend friends-list balance (item 5)

B1. **Add `balance` to `FriendItem`.**
    `balance: { net: Decimal, settlement_status: SettlementStatus }`.

B2. **Bulk pair-balance helper.**
    New function `txn_service.compute_pair_balances_for(
    requester_id, friend_ids)` that fetches
    `query_user_member_rows(requester_id)` once, then for each
    friend fetches their txns, intersects, and computes via
    `balance.compute_pair_balance`. Returns a dict
    `{friend_id -> BalanceResult}`.

B3. **Wire into `friends.service.list_friends`.**
    After hydrating the page, call the bulk helper for the page's
    friend ids, attach `balance` to each `FriendItem`. Empty
    intersection → `(0.00, settled, None)`.

B4. **Tests.** Friends with shared txns return correct balances;
    no shared txns → settled; soft-deleted txns ignored;
    cross-pair isolation (other friends' balances don't leak).

B5. **Coverage gate.**

## Phase C — Backend transaction comments (item 3)

C1. **Comment row class in repository.**
    - `put_comment(txn_id, comment_id, author_id, body, kind,
      created_at)`.
    - `query_comments(txn_id, limit, last_sk)` ASC by SK.
    - `new_comment_id()` (ULID).

C2. **Comment models + errors.**
    `Comment`, `CreateCommentRequest`, `ListCommentsResponse`.
    Errors: `CommentBodyTooLongError`, `CommentBodyEmptyError`.
    Constants: `COMMENT_MAX = 1000`, `COMMENT_LIST_DEFAULT = 50`,
    `COMMENT_LIST_MAX = 100`.

C3. **Comment service + routes.**
    - `post_comment(requester_id, txn_id, body) -> Comment`:
      check membership (404 mask if non-member), validate body,
      put row, return.
    - `list_comments(requester_id, txn_id, limit, cursor)`: same
      membership check, paginated.
    - Routes `POST /v1/transactions/{id}/comments`,
      `GET /v1/transactions/{id}/comments`.

C4. **System comment on update.**
    - `comments.build_edit_summary(prior_snapshot, new_inputs)` —
      pure function that produces a multi-line diff string. Skips
      keys that didn't change. Returns None on semantic no-op.
    - In `service.update_transaction`, after the META update
      succeeds, call `repository.put_comment(...,
      author_id="system", kind="system", body=summary)` inside a
      try/except — log on failure, never re-raise.
    - Tests: comment is appended on every distinct edit; no
      comment on no-op edit; failure path doesn't break the update.

C5. **Tests for comments.**
    Membership masking, body length, empty body, pagination,
    system comment shape, list ordering.

C6. **Coverage gate.**

## Phase D — OpenAPI + SDK regeneration

D1. **Regenerate `packages/openapi/openapi.yaml` + SDK.**
    `make openapi` (or equivalent). Commit both.

D2. **Verify CI drift gate** clean by running gate locally.

## Phase E — Frontend bugfixes + new UI

E1. **`useUpdateMyProfile` mutation + Settings page name edit.**
    Inline edit on the Profile card; on save invalidate `auth-user`
    + call `refreshUser`. Toast on success. Field-error mapping for
    422.

E2. **Friends list — show balance.**
    Replace the hardcoded "Settled" with derived label from
    `balance.settlement_status` + `balance.net` + `currency`.

E3. **Friend remove — toast on `BALANCE_NOT_SETTLED`.**
    `FRIENDLY` map on the friend-detail screen + friends list
    remove path. Pretty toast: "Settle the balance with this
    friend before removing them."

E4. **Reset-password — friendly text for `PASSWORD_REUSED`.**
    Add `FRIENDLY.PASSWORD_REUSED = "New password must be
    different from your current password."`.

E5. **Dashboard summary cards — `my_paid - my_owed`.**
    Rewrite the loop in `SummaryCards.tsx`. Drop `creator_id`
    branch.

E6. **Transaction comments UI.**
    - `useTransactionComments(txnId)` query + `usePostComment`
      mutation in `lib/queries/transactions.ts`.
    - New `components/transactions/CommentList.tsx` and `Composer`
      sub-components. System comments distinct styling.
    - Wire into `app/(app)/transactions/[txnId].tsx`.

E7. **Tests.** Vitest + RNTL component tests for each new UI piece;
    update SummaryCards test for new math.

E8. **Coverage gate** on the client.

## Phase F — Docs + lint + final

F1. **Update feature READMEs.**
    `me/README.md`, `friends/README.md`, `transactions/README.md`,
    `auth/README.md` for the new endpoints/fields.

F2. **Update root README.md** if any new env var or run-step was
    introduced (not expected here, but verify).

F3. **Run full test suite + ruff/biome/mypy/tsc** locally; fix.

F4. **Open PR (no auto-merge).** PR body lists the six items.
