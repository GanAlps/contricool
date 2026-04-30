# Phase 7b — UX Bugfixes + Transaction Comments — Change Details

## Overview

A focused set of post-launch UX fixes plus a small new feature
(transaction comments). Six items grouped into one spec because they
are all small/medium changes touching adjacent areas; treating them
together avoids six separate PRs against parts of the same code paths.

Six items:

1. Settings: editable display name (email + currency stay read-only).
2. Friends: cannot remove a friend with a non-zero outstanding balance.
3. Transactions: members can post free-form comments; system auto-posts
   a comment whenever the transaction is edited, summarising what
   changed.
4. Auth: password reset returns a friendly error when the new password
   is the same as the current one (instead of a generic "unknown
   error").
5. Friends list: each row shows the real net balance against that
   friend, not a hardcoded "Settled".
6. Dashboard summary: "you owe" / "you're owed" cards compute from
   `payers` (was: from `creator_id`, which is wrong for txns the
   requester logged on a friend's behalf).

The complexity for each is **SIMPLE** except item 3 which is **MEDIUM**
(new DDB row class, two new endpoints, server-emitted system row,
client UI). Treated below in one combined doc rather than splitting
because they merge into one PR.

---

## Item 1 — Editable display name

### Behaviour

- New endpoint `PATCH /v1/me/profile` body `{name: str}`.
- `name`: 1..80 chars, non-blank after trim, the same regex/Pydantic
  rules already used at signup.
- Email and `currency` are not part of the body and cannot be changed
  through this endpoint (or any other for now).
- Returns the updated profile shape `{user_id, name, currency}`.
- Settings page gets an inline edit on the Profile card; on save we
  toast and refresh the auth user (so name appears immediately on the
  dashboard greeting).

### Server detail

- Update the `META` row of `ContriCool-Users-<env>`: `SET name = :n,
  updated_at = :now` with `attribute_exists(PK) AND status <> "deactivated"`.
- No Cognito mutation — the user's name is server-owned, not a Cognito
  attribute (already true today). We don't mirror it back to Cognito
  custom attrs.
- Re-uses the auth feature's name validator
  (`apps/api/app/features/auth/service.py::_validate_name` if exposed,
  otherwise inline the same rule on the `me` route).

### Client detail

- New `useUpdateMyProfile` mutation in `lib/queries/me.ts`.
- Settings page Profile card flips to an Input + Save/Cancel when the
  user taps "Edit name". On success: invalidate `auth-user` query and
  call `useAuthStore.refreshUser()` so the cached user reflects the
  change.

### Edge cases

- Empty/whitespace-only name → 422 VALIDATION_ERROR.
- Same name as current → still 200 (no-op-ish, simpler than a 304).
- Deactivated account (status != active) → 403 — but that user
  cannot reach the screen anyway; defensive.

---

## Item 2 — Block friend removal when balance is non-zero

### Behaviour

- `DELETE /v1/friends/{user_id}` now refuses with **409
  `BALANCE_NOT_SETTLED`** when the requester's net balance with the
  friend is not within ±0.01 of zero.
- The error response carries `details: [{field: "balance", issue:
  "Settle the balance with this friend before removing them."}]` plus
  `message` for screen reader.
- Friends detail screen surfaces a friendly toast: "You owe / are owed
  X — settle up before removing."
- Friends list "Remove" path (if exposed) uses the same toast.

### Server detail

- Inside `friends.service.remove_friend`, before calling
  `repo.delete_friendship`, call the existing
  `txn_service.compute_pair_balance` and reject if `status_ != "settled"`.
- New error class `BalanceNotSettledError` in
  `app.features.friends.errors`.

### Edge cases

- Soft-deleted transactions are already excluded by
  `compute_pair_balance` — no extra logic needed.
- Friend with no shared transactions → balance is 0 → settled →
  removal proceeds.
- Self-remove still 422 (unchanged).

---

## Item 3 — Transaction comments + system audit comments

### Behaviour

- Any **member** of a transaction can post a comment.
  `POST /v1/transactions/{txn_id}/comments` body `{body: str}` →
  201 with the new comment.
- `GET /v1/transactions/{txn_id}/comments?limit=&cursor=` returns the
  comment list, oldest-first, paginated.
- When a transaction is updated via `PUT /v1/transactions/{txn_id}`,
  the server appends a **system comment** whose `kind = "system"` and
  whose `body` is a human-readable diff summary of what changed
  (name, amount, currency, txn_date, note, split_method, payers, members).
- Comments are immutable: no edit/delete in this iteration. Trade-off
  noted for future work.

### Data model

New row class on `ContriCool-Transactions-<env>`:

| Item     | PK              | SK                          |
|----------|-----------------|-----------------------------|
| COMMENT  | `TXN#<txn_id>`  | `COMMENT#<ulid>`            |

Attrs: `author_id` (str — `"system"` for server comments), `body`
(str ≤ 1000 chars), `kind` (`"user" \| "system"`), `created_at`
(ISO8601). ULID monotonic so the SK doubles as a creation cursor.

### Endpoints

- `POST /v1/transactions/{txn_id}/comments` — 201, body
  `{comment_id, txn_id, author_id, body, kind: "user", created_at}`.
  - Validates: requester is a member; body length 1..1000 after trim;
    not blank.
  - 404 if non-member (mask).
- `GET /v1/transactions/{txn_id}/comments` — 200,
  `{items: Comment[], next_cursor: str|null}`.
  - 404 if non-member.
- System comments are emitted inline in `service.update_transaction`
  after the META/MEMBER write succeeds. They are best-effort: a
  system-comment write failure is logged but does NOT roll back the
  edit (so a transient DDB error on the comment row never blocks a
  successful edit).

### Diff summary format

`build_edit_summary(prior, current)` produces lines like:

```
Updated transaction:
- amount: 100.00 → 120.00
- name: "Lunch" → "Lunch + dessert"
- members: added Alex, removed Sam
- payers: changed
```

If only `updated_at` differs (semantic no-op), the system comment
is suppressed.

### Client detail

- Transaction detail screen renders a "Comments" section: list +
  composer (one-line text + post button).
- Member-only: composer hidden for non-members (defensive — users
  shouldn't be able to reach the screen, but render-time check keeps
  the UI honest).
- System comments rendered with a different bg/icon.

### Trade-offs

- **System comment as a row, not derived from AUDIT rows.** AUDIT
  rows already capture full snapshots; we *could* render them as
  comments in the UI by reading them. We don't because: (a) AUDIT
  rows aren't author-attributed in the right shape; (b) the future
  desire to delete/edit user comments is easier on a dedicated row
  class; (c) AUDIT TTL purges them at 30 days, but we want comments
  to live for the lifetime of the transaction.
- **Best-effort system comments.** A failed system-comment write
  shouldn't 5xx the edit. We log + move on; users see the META
  edit succeed but no system row appended. Acceptable at MVP scale.
- **No real-time push.** Comment list is fetched on screen mount
  + after each successful POST; TanStack Query invalidation handles
  refresh. Live updates are out of scope.

---

## Item 4 — Friendly error for password-reset reuse

### Behaviour

- Client submits `POST /v1/auth/reset-password` with new password ==
  current password → server returns 422 `PASSWORD_REUSED` (new code)
  with message "New password must be different from your current
  password."
- Client surfaces it as a banner on the reset screen.

### Server detail

- Cognito raises `InvalidParameterException` with message containing
  "Password should differ from previous password" on this case (and
  `LimitExceededException` after enough attempts — already mapped to
  RATE_LIMITED).
- In `cognito_client._map_error`, on `path == "reset_password"` and
  `code == "InvalidParameterException"` whose `Message` contains the
  word "different" / "differ" / "previous", return a new
  `PASSWORD_REUSED` AuthError (422). Other `InvalidParameterException`
  on this path falls back to the existing 422 `INVALID_PASSWORD`
  rather than the wrong 409 `ALREADY_CONFIRMED`.

### "Allow user to keep old password"

The user requested this be tried "if easily possible without
complicated changes". It is **not** easily possible: Cognito does not
allow `confirm_forgot_password` to set the same hash, and attempting
to bypass that would require running our own credential store. We
explicitly *do not* do that. Instead, the friendlier error message
gives the user clear guidance.

### Client detail

- `FRIENDLY` map in `app/(auth)/reset-password.tsx` adds
  `PASSWORD_REUSED: "New password must be different from your
  current password."`.
- No new screen.

---

## Item 5 — Friends list shows real balance

### Behaviour

- `GET /v1/friends` response items now include
  `balance: { net: Decimal, settlement_status: SettlementStatus }`.
  Currency stays at the existing `currency` field.
- Friends list row renders:
  - "Settled" if `settlement_status == "settled"`.
  - "Owes you X CUR" if `friend_owes`.
  - "You owe X CUR" if `you_owe`.

### Server detail

- The list endpoint pre-fetches the requester's `query_user_member_rows`
  ONCE (capped at 500). For each friend in the page, intersect that
  set with the friend's `query_user_member_rows`, hydrate META +
  members for the intersection, and compute pair-balance.
- This is N additional queries for N friends; with the page size
  capped at 100 and `compute_pair_balance` already designed to
  receive a list, the cost is bounded. Trade-off discussed below.

### Trade-offs

- **N queries per page.** Acceptable at MVP scale (most users have
  <20 friends). If this becomes a hotspot, denormalise net-balance
  onto the friendship row at write-time (every transaction write
  updates 2 friendship rows). Not done now: deferring write-time
  denormalisation until we see real read pressure.

### Edge cases

- A friend with no shared transactions returns `net=0, status=settled`
  (compute_pair_balance already handles this).
- Soft-deleted txns are skipped, matching the friend-detail screen.

---

## Item 6 — Dashboard summary card calculation

### Behaviour

- "You owe" + "You're owed" reflect actual pay-vs-owe imbalance, not
  a `creator_id`-based proxy.
- Concretely, for each transaction in the recent list (the data the
  dashboard already loads):
  - `net = my_paid_amount - my_owed_amount`
  - `net > 0` → `youAreOwed += net`
  - `net < 0` → `youOwe += abs(net)`
- Values match the user's intuition: friend paid, I owe → owe goes up;
  I paid, friend owes → owed goes up.

### Server detail

- `TransactionListItem` gains a `my_paid_amount: Decimal` field
  (sum of `paid_amount` across `meta.payers` rows where
  `user_id == requester_id`; 0 if requester didn't pay).
- `service.list_transactions` populates it from the existing META
  payers list — no extra query.
- Existing OpenAPI schema regenerates; SDK regenerates.

### Client detail

- `components/transactions/SummaryCards.tsx` rewrites the for-loop to
  use `my_paid_amount - my_owed_amount`. Drops the `creator_id`
  branch entirely.
- Test updates to assert new behaviour against transactions where
  `creator_id == me` but `me ∉ payers` (and vice-versa).

### Edge cases

- Settlement transactions: same logic — `my_paid - my_owed`. A
  settlement where I "paid back" is treated as an owe-decrease,
  which is right.
- Currency mismatch: dashboard already assumes a single currency
  (the user's). Mixed-currency transactions are out of scope.

---

## Summary of file touches

Backend (Python):
- `apps/api/app/features/me/{models,routes,service,repository}.py` — PATCH profile
- `apps/api/app/features/friends/{errors,service}.py` — block remove on balance
- `apps/api/app/features/friends/models.py` — balance on FriendItem
- `apps/api/app/features/friends/service.py` — list with balances
- `apps/api/app/features/transactions/{models,routes,service,repository}.py` — comments,
  system comment on update, my_paid_amount on list item
- `apps/api/app/features/auth/cognito_client.py` — PASSWORD_REUSED mapping
- New: `apps/api/app/features/transactions/comments.py` (diff summary)
- Tests for each, mirror layout.

Frontend (TS):
- `apps/client/lib/queries/{me,friends,transactions}.ts`
- `apps/client/app/(app)/settings.tsx` — name edit
- `apps/client/app/(app)/friends/index.tsx` — balance per row
- `apps/client/components/transactions/SummaryCards.tsx` — fix calc
- `apps/client/app/(app)/transactions/[txnId].tsx` — comments
- `apps/client/components/transactions/CommentList.tsx` (new)
- `apps/client/app/(auth)/reset-password.tsx` — FRIENDLY map
- Tests.

OpenAPI + SDK regeneration: yes (new endpoints + new fields).
