# Phase 4c — Transactions Frontend UI — Tasks

## Stratum 1 — SDK aliases + types + queries

### T1 — Extend `packages/client-sdk/src/index.ts`
Add the transactions surface aliases (`CreateTransactionRequest`,
`Transaction`, `ListTransactionsResponse`, `TransactionListItem`).
Run `make openapi` so `packages/openapi/openapi.yaml` and the
`schema.d.ts` stay in sync.

### T2 — Re-export in `apps/client/lib/types.ts`
Mirror the friends pattern: pull the new SDK aliases into client-
local names.

### T3 — `apps/client/lib/schemas.ts` adds `AddTransactionSchema`
Structural Zod schema with `superRefine` for cross-field invariants
(positive amount, payers ⊆ members, paid-sum == amount, percent-sum
100, settlement shape).

### T4 — `apps/client/lib/splits.ts` (client)
Tiny helper mirroring the server's `equal`/`share`/`percent`
last-member-absorbs-remainder rounding so the form preview matches
the server exactly. Decimal.js or BigInt micro-impl, whichever
keeps the bundle smaller — start with a stringified-cents `BigInt`
implementation; no new deps.

### T5 — `apps/client/lib/queries/transactions.ts`
- `transactionsKeys` keys map.
- `useTransactions({ limit, cursor, friend_id })`.
- `useTransaction(txnId)`.
- `useCreateTransaction()` accepting `{ body, idempotencyKey }`,
  invalidating `['transactions']` + every member's
  `['friend-balance', uid]` on success.

### T6 — Hook unit tests
`apps/client/__tests__/lib/queries-transactions.test.tsx` —
happy + one error per hook. Mirror friends tests.

## Stratum 2 — MSW handlers + UI components

### T7 — Extend `apps/client/__tests__/msw-handlers.ts`
Add the `/transactions` GET, `/transactions/{txn_id}` GET,
`/transactions` POST handlers with the typed envelope shape +
`set-cookie` semantics that match the backend.

### T8 — `components/transactions/AddTransactionSheet.tsx`
RHF + Zod, sections per requirements §R3, idempotency-key
lifecycle via `useRef`. Submit calls `useCreateTransaction`.
Friendly error mapping per design.md.

### T9 — `components/transactions/TransactionRow.tsx`
Reusable list row (name + amount + sign + date), used by the
dashboard recent list and the transactions list page.

### T10 — `components/transactions/SummaryCards.tsx`
Two cards (you owe / you're owed) with the recent-50 client roll-
up. Skeleton state while the list query is loading.

### T11 — Component unit tests
- AddTransactionSheet happy + validation + error-mapping cases.
- TransactionRow rendering snapshot.
- SummaryCards rendering across positive/negative/zero balances.

## Stratum 3 — Routes

### T12 — `app/(app)/transactions/index.tsx`
List screen with filter chip + "Load more" pagination.

### T13 — `app/(app)/transactions/[txnId].tsx`
Detail screen + 404 mask.

### T14 — Update `app/(app)/dashboard.tsx`
Drop the placeholder; render `SummaryCards` + recent activity +
"Add transaction" CTA. Sign-out moves to the topbar (already
there).

### T15 — Update `app/(app)/friends/[userId].tsx`
Replace the zero-balance placeholder with real data. Add
per-friend transactions list + "Add transaction" CTA prefilled
with this friend.

### T16 — Top-bar nav link for "Transactions"
`apps/client/app/(app)/_layout.tsx` gets a third NavLink so
desktop users can reach the transactions list directly.

### T17 — Route tests
- list.test.tsx — renders, paginates, filter chip switches.
- detail.test.tsx — renders full + 404 mask.
- dashboard.test.tsx (updated).
- friends/detail.test.tsx (updated).

## Stratum 4 — Polish

### T18 — Update `EXECUTION_PLAN.md`
Mark 4c complete in the sub-phase table and the goal block.

### T19 — Run the full suite
- `pnpm --filter @contricool/client test` (Vitest + RTL).
- `pnpm --filter @contricool/client typecheck` (`tsc --noEmit`).
- `pnpm --filter @contricool/client-sdk build` (regen schema).
- Ensure no biome warnings.

### T20 — Open PR `feat/phase-4c-transactions-client`
- Branch off `main`.
- Conventional Commit on the squash:
  `feat(client): Phase 4c — transactions UI (list/detail/new + dashboard)`.
- Body links the spec folder.
- Wait for CI green.

### T21 — pr-code-reviewer pass
- Invoke pr-code-reviewer; address blocking findings; re-review
  until approved.

### T22 — Watch CI; fix any failures.

## Out of scope

- Edit / delete / restore — Phase 5.
- Multi-currency — post-MVP.
- Native (iOS/Android) UI polish — post-MVP via Expo build.
