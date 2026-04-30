# Phase 4c — Transactions Frontend UI — Requirements

## Overview

Phase 4c puts a real UI on the transactions backend delivered in
Phase 4b. After this lands, an Expo (web + native) user can:

- See a dashboard with summary cards ("you owe / you're owed") and a
  recent-activity list.
- Browse all of their own transactions in a paginated list, with an
  optional filter chip restricting to a specific friend.
- Read any individual transaction in full (members, owed amounts,
  payers, totals).
- Open a friend's detail page and see the **real** net balance plus
  the list of transactions with that friend.
- Tap "Add transaction" anywhere and run through a Hook-Form-driven
  modal that mirrors the server's validation surface, then submits
  with a client-minted `Idempotency-Key` and pessimistically picks
  the right friendly error message for each backend code.

Phase 5 will add edit / delete / restore. The UI here is read +
create only.

This phase realises EXECUTION_PLAN.md sub-section **4c**, sources
its semantics from **Designs 6 (transaction domain), 8 (API), 10
(frontend UI/state)**, and consumes the regenerated TypeScript SDK
in `packages/client-sdk`.

## Requirements

### R1 — Dashboard route (`app/(app)/dashboard.tsx`)

The dashboard is the post-login landing page (already wired in the
existing Phase 2d auth flow). After 4c:

- Two **summary cards**: "Total you owe" and "Total you're owed",
  computed by aggregating the requester's `my_owed_amount` minus
  their `paid_amount` proportions across the most recent 50
  non-deleted transactions. (Approximation; pair-balance API gives a
  precise number per friend, but a single home-page roll-up across
  every friend doesn't have a backend route at MVP.)
- A **recent activity list** (last 10 transactions, newest first),
  each row tappable → opens the transaction detail.
- An **"Add transaction"** primary CTA opens the create-transaction
  modal/sheet on web and a full-screen modal on native.
- Empty state (no transactions yet): single card with the same CTA.
- Existing dashboard "Welcome, {name}" header + sign-out are kept
  but reflowed so the summary cards are above the fold.

### R2 — Transactions list route (`app/(app)/transactions/index.tsx`)

- Paginated list of all transactions where the requester is a member,
  newest first, served by `GET /v1/transactions`.
- Optional **filter chip** at the top: "All", "With <friend>".
  Selecting a friend chip re-issues the query with `?friend_id=…`
  and updates the URL so a refresh / share preserves the filter.
- Cursor-based pagination: "Load more" button at the bottom while
  `next_cursor` is present.
- Empty state: "No transactions yet — tap Add transaction to record
  your first one."
- Loading + error states match the friends-list pattern (Spinner,
  banner card with retry).

### R3 — Add-transaction modal (`components/transactions/AddTransactionSheet.tsx`)

Used from the dashboard, the list, and the friend detail page.

- React Hook Form + Zod schema (`AddTransactionSchema`) mirroring the
  server's `CreateTransactionRequest`.
- Sections, in order:
  1. **Name** (1..120 chars, trimmed).
  2. **Amount** + currency badge (currency = requester's
     `auth-store.user.currency`; locked, non-editable at MVP).
  3. **Date** (defaults to today; ISO date input on web; native uses
     `<input type=date>` via `expo-router`-friendly fallback).
  4. **Type** segmented control (Expense / Settlement); changing to
     Settlement collapses members to 2 + payer to 1 + split to amount
     and surfaces help-text.
  5. **Members** picker (multi-select from the requester's friends;
     creator is always included; cap 10). Tapping a chip removes a
     member.
  6. **Paid by** subset selector — defaults to the requester (single-
     payer expense is the common case); switching to "Multiple" reveals
     a per-payer amount editor.
  7. **Split method** segmented control (Equal / Amount / Share /
     Percent); changing it shows or hides the per-member input rows.
  8. **Note** (optional, 0..500 chars).
- A **client-minted `Idempotency-Key`** (`crypto.randomUUID()`) is
  attached on every submit; the same key is reused on a retry within
  the same modal lifetime so a transient network error doesn't
  duplicate a transaction.
- On submit:
  - 201 → close, toast "Added <name>", invalidate queries
    `['transactions']` + `['friend-balance']` for every involved
    friend.
  - `NOT_FRIEND` (422) → inline banner: "One or more selected
    members aren't your friend anymore."
  - `CURRENCY_MISMATCH` (422) → inline banner: "<friend> uses a
    different currency. Remove them or change the transaction's
    currency." (Currency is locked at MVP, so the message reduces
    to "Remove them.")
  - `OWED_SUM` / `PERCENT_SUM` / `PAID_SUM` → field-level error on
    the relevant section.
  - `INVALID_AMOUNT` / `INVALID_DATE` → field-level error.
  - `IDEMPOTENCY_KEY_REUSED` (409) → toast: "This transaction was
    already created. Refresh to see it." (very rare in practice;
    only happens if the user changes the form mid-submit).
  - Any other 422 with a `details[]` payload → inline banner with the
    first detail.
  - Network / 5xx → toast: "Couldn't save the transaction. Try again."

### R4 — Transaction detail route (`app/(app)/transactions/[txnId].tsx`)

- Read-only detail view: name, amount + currency, date, type, split
  method, note.
- Per-member rows showing display name (looked up from the
  friends-list cache + the requester's own profile) and
  `owed_amount`.
- Per-payer rows showing display name and `paid_amount`.
- Audit "Created by <name> on <date>" line.
- Back button + a placeholder **"Edit"** button disabled with
  "(coming soon)" — Phase 5 will enable.
- 404 → friendly card "This transaction doesn't exist or you can't
  see it."

### R5 — Friend detail integration (`app/(app)/friends/[userId].tsx`)

The Phase 3b placeholder balance is replaced with real data:

- The balance card shows the actual `net` and renders one of three
  states:
  - `settled` → "Settled" + 0.00 in their currency.
  - `friend_owes` → "Friend owes you <abs(net)>" (positive value
    rendered without a leading minus).
  - `you_owe` → "You owe friend <abs(net)>".
- Below the card, a **Pattern #9** transactions list (`?friend_id=…`)
  with the same row layout as the dashboard's recent activity.
- "Add transaction" CTA opens the AddTransactionSheet pre-filled
  with this friend in `members` and the requester as `paid_by`.

### R6 — TanStack Query hooks (`lib/queries/transactions.ts`)

| Hook | Purpose | Cache key |
|---|---|---|
| `useTransactions(opts)` | List all my txns; opts has `limit`, `cursor`, `friend_id` | `['transactions', { limit, cursor, friend_id }]` |
| `useTransaction(txnId)` | Single txn detail | `['transaction', txnId]` |
| `useCreateTransaction()` | Mutation; on success invalidates `['transactions']`, `['transaction']`, every relevant `['friend-balance', uid]` | n/a |

Friends-feature `useFriendBalance` is **left as is** (already returns
the real number now that backend Phase 4b is live). 4c only ensures
the UI renders the populated fields.

### R7 — Schemas (`lib/schemas.ts`)

Add `AddTransactionSchema` mirroring the server's per-method
invariants enough to short-circuit obvious errors (positive amount,
non-empty name, ≥2 members, payer ⊆ members, payer-paid-sum equals
amount, percent sums to 100). The server is still authoritative —
the schema is a UX-fast-fail, not a security boundary.

### R8 — Idempotency-Key handling

- The `apiClient` SDK accepts a `headers` option per call. The
  `useCreateTransaction` mutation accepts an `idempotencyKey` arg
  on every `mutateAsync` invocation; the form mints one on first
  submit (`crypto.randomUUID()`), stashes it in a ref, and reuses
  the same value across retries until the modal closes.
- The same key is **never** auto-generated inside the hook to keep
  retry semantics explicit — the form owns the lifetime.

### R9 — Tests

- Component tests for `AddTransactionSheet`:
  - Happy path: equal-split 2-member submit invokes mutation with
    the right body shape + idempotency-key header; on 201, closes
    and toasts.
  - Validation: zero amount → field error; selecting a single
    member → field error; settlement type collapses to 2 members.
  - Server-error mapping: `NOT_FRIEND` → banner; `CURRENCY_MISMATCH`
    → banner; `IDEMPOTENCY_KEY_REUSED` → toast.
- Component tests for the dashboard summary cards (with seeded
  transaction list).
- Component tests for the transactions list filter chip behaviour.
- Component tests for the friend detail real-balance render across
  `settled` / `friend_owes` / `you_owe`.
- Hook tests for `useTransactions`, `useTransaction`,
  `useCreateTransaction` (mirror the friends queries-test layout).
- MSW handlers for `/transactions`, `/transactions/{id}` extended
  with the typed envelope shape.

### R10 — Out of scope (forward links)

- Edit transaction → Phase 5.
- Delete / restore → Phase 5.
- Audit-row read screen → Phase 5.
- Multi-currency → post-MVP (currency stays locked to the
  requester's `auth-store.user.currency`).

## Edge cases

- **Friend currency mismatch in the picker**: filter the friend-
  picker chip list to only friends sharing the requester's
  currency, with a footnote "Friends in another currency aren't
  shown." Avoids the user composing an invalid transaction the
  server would reject.
- **Member list cap**: the picker disables further selections
  past 10 members and shows a small "Max 10 members" hint.
- **Equal-split rounding preview**: the form previews the
  per-member owed_amount client-side using the same
  `last-member-absorbs-remainder` rule the server uses, so what
  the user sees matches what gets persisted.
- **Settlement type guards**: switching to Settlement with > 2
  members already chosen reverts to the requester + the
  most-recently-selected friend; reverting back to Expense
  restores the prior member list (best-effort UX).
- **"Add transaction" deeplink from a friend page** prefills with
  that friend; user can still add or remove members.

## Summary

Phase 4c delivers the transaction UX surface — dashboard,
list, detail, add-transaction modal — wired to the regenerated
SDK. Phase 5 then layers edit/delete/restore on top. Together, 4a
+ 4b + 4c = the full Phase 4 deliverable described in
EXECUTION_PLAN.md.
