# Phase 3b — Friends Client UI — Requirements

## Overview

Phase 3b ships the **Expo client UI for friends** on top of the
Phase 3a backend. After 3b, an authenticated user can — entirely from
the deployed web bundle — see their friend list, add a new friend by
email, view a per-friend detail page with the (zero-for-now) balance,
and remove a friendship.

## Scope

### In scope (this phase)

- New routes under `apps/client/app/(app)/friends/`:
  - `index.tsx` — friend list page with empty state, "Add friend" CTA,
    and per-friend balance preview.
  - `[userId].tsx` — per-friend detail with name, balance, "Remove
    friend" CTA, "Settle up" placeholder (Phase 4).
- Add-friend modal triggered from the list page — email input, RHF +
  Zod validation, error mapping for 400/404/409/422/429.
- Auth-aware nav update on `(app)/_layout.tsx`: a `Friends` link in
  the top bar so the dashboard isn't a dead end.
- `lib/queries/friends.ts` — TanStack Query hooks wrapping the SDK
  methods (`useFriends`, `useFriendBalance`, `useAddFriend`,
  `useRemoveFriend`). Query keys, optimistic updates, cache
  invalidation.
- `lib/schemas.ts` adds `AddFriendSchema` mirroring the backend
  `AddFriendRequest` (with the same lenient `str` for email — the
  service layer distinguishes phone-shape from malformed-email).
- Tests for every new component + hook: positive happy path + every
  Phase 3a negative on the relevant screen.
- Updated `apps/client/README.md` with the new route inventory.

### Out of scope (later phases)

- Real balance numbers (Phase 4 wires the transactions table; this
  phase ships the UI shape that already renders zeros from the
  Phase 3a `/balance` endpoint).
- "Settle up" CTA on the friend detail page is a stub link — Phase 4
  routes it.
- Friend requests / accept-decline / blocks (deferred per Design 6).
- Native (iOS/Android) — the screens are RN-Web compatible already
  but EAS native builds ship later.
- Search / sort on the friend list (alphabetical sort by `name` is
  fine for the MVP friend-count scale; a search box waits until users
  ask).
- Pagination UI affordance — the SDK returns `next_cursor` and we'll
  wire `useInfiniteQuery` only if a real user crosses 50 friends.
  At MVP scale this is essentially never; a single-page render is
  fine.

## Functional Requirements

### R1 — Friend list page (`/friends`)

- **R1.1** — Authenticated route under `(app)/_layout.tsx`. Unauth
  visitors are redirected to `/login` by the existing guard.
- **R1.2** — On mount, calls `useFriends()` which dispatches
  `apiClient.GET('/friends', {params: {query: {limit: 50}}})`.
- **R1.3** — **Loading state**: Spinner centered.
- **R1.4** — **Empty state**: Card with copy "No friends yet — add
  one to start tracking expenses." and an "Add friend" button that
  opens the modal.
- **R1.5** — **Populated state**: vertical list, each row shows:
  - Friend name (left).
  - Currency badge.
  - Balance summary right-aligned (Phase 3b renders "Settled" since
    `net=0` is the only return shape; Phase 4 renders signed amounts).
  - Tap → navigate to `/friends/[userId]`.
- **R1.6** — A persistent "Add friend" CTA in the top-right (button or
  FAB-style on narrow widths).
- **R1.7** — **Error state**: API error banner with retry button.
  Stable codes mapped via `lib/error-mapping.ts`:
  - `RATE_LIMITED` → toast with `Retry-After`.
  - 5xx → generic toast.
  - Otherwise → banner with friendly message.

### R2 — Add-friend modal

- **R2.1** — Opens from the list-page CTA. Backed by
  `react-native-reusables` `Sheet` (mobile-friendly modal).
- **R2.2** — Form fields: `email` (text, required, autocomplete=email,
  inputMode=email).
- **R2.3** — Zod schema `AddFriendSchema`:
  - `email` is `z.string().trim().min(1, 'Required')` — lenient,
    matches the backend contract that distinguishes phone-shape
    (400) from malformed-email (422).
- **R2.4** — Submit calls `useAddFriend()` mutation.
  - Optimistic invalidation of `['friends']` query on success.
  - Modal closes on success; toast "Added <name>".
- **R2.5** — Error mapping:
  - `INVALID_IDENTIFIER` → field error "Friends are added by email
    only — phones aren't supported yet."
  - `USER_NOT_FOUND` → field error "We couldn't find anyone with that
    email."
  - `CONFLICT` → field error "You're already friends."
  - `SELF_ADD_FORBIDDEN` → field error "You can't add yourself."
  - `VALIDATION_ERROR` → field-level message from `details[0].issue`.
  - `RATE_LIMITED` → toast with `Retry-After` ("Try again in N seconds").

### R3 — Friend detail page (`/friends/[userId]`)

- **R3.1** — Authenticated. Reads `userId` from query params.
- **R3.2** — Fetches in parallel:
  - The friend's identity (read from the `useFriends()` cached list
    where possible — falls back to the friend's name from the URL
    state if cache is cold).
  - The balance via `useFriendBalance(userId)` →
    `apiClient.GET('/friends/{user_id}/balance', {params: {path: {user_id}}})`.
- **R3.3** — Renders:
  - Friend name + currency + balance (zero for now).
  - "Remove friend" button (destructive variant). Tapping → confirm
    dialog → on confirm calls `useRemoveFriend()`.
  - "Settle up" button — disabled at MVP, with a small "(coming
    soon)" badge.
- **R3.4** — On remove success: navigate back to `/friends`, toast
  "Removed <name>", invalidate `['friends']` cache.
- **R3.5** — Error states:
  - 404 → "This friend doesn't exist or you're no longer friends" +
    "Back to friends list" CTA.
  - Other → generic banner + retry.

### R4 — Top-bar nav update

- **R4.1** — `(app)/_layout.tsx` shows nav links:
  Dashboard / **Friends** / Sign out.
- **R4.2** — Active route is highlighted via NativeWind `active:`
  styling.
- **R4.3** — On narrow widths (web < 768px) the links collapse into a
  hamburger menu (use the existing primitives if available, else a
  simple inline list — not a hard requirement at MVP).

### R5 — TanStack Query wiring (`lib/queries/friends.ts`)

- **R5.1** — Hooks exposed:
  - `useFriends(opts?)` — `{ items, fetchNextPage, hasNextPage }`.
    Phase 3b uses single-page mode (`limit=50`); the hook is shaped
    so Phase 4+ can switch to `useInfiniteQuery` without API churn.
  - `useFriendBalance(userId)` — `{ data, isLoading, error }`.
  - `useAddFriend()` — mutation. Invalidates `['friends']` on success.
  - `useRemoveFriend()` — mutation. Invalidates `['friends']` and
    `['friend-balance', userId]` on success.
- **R5.2** — Query keys (centralised in the same file):
  - `['friends', { limit }]`.
  - `['friend-balance', userId]`.
- **R5.3** — `staleTime`: 30 s for the list; 0 for balance (will be
  hot once Phase 4 lands).

## Non-functional Requirements

### NFR1 — Type safety

- **NFR1.1** — All four endpoints called via the SDK with full path
  + body type-checking. No `any`, no `as unknown as` casts in
  production code (allowed in tests where the SDK's overload
  resolution is overly strict).
- **NFR1.2** — `lib/types.ts` re-exports the four new shapes as
  friendly aliases (`FriendItem`, `FriendBalance`, etc.) so screens
  don't reach into `paths['/friends']…` directly.

### NFR2 — Testing

- **NFR2.1** — Coverage thresholds unchanged: `lib/**` 99%/95%,
  `app/**` 80%/70%, `components/**` 80%/70%.
- **NFR2.2** — Tests live in `apps/client/__tests__/app/friends/` and
  mirror the source tree.
- **NFR2.3** — MSW handlers added for all four `/v1/friends/*` paths
  in `__tests__/msw-handlers.ts`. Per-test overrides for negatives.

### NFR3 — Privacy / no leaks

- **NFR3.1** — The list / detail pages never display anything beyond
  `name`, `currency`, `balance summary`. **No email, no phone, no
  user_id surfaced in human-readable copy** (user_id appears only in
  URLs, which is unavoidable).
- **NFR3.2** — Console / log redaction: no test asserts on raw email
  in console (the API is the source of truth for redaction; client
  has no PII to redact).

### NFR4 — Bundle budget

- **NFR4.1** — The new screens shouldn't push us past the existing
  hard limit (350 KB gz). TanStack Query is already in the bundle;
  the new code is shaped data + a few primitives = ~5–10 KB gz worst
  case.
- **NFR4.2** — CI bundle-size gate continues to enforce.

## Negative-test Requirements

Each tested with MSW per-test overrides on the matching screen.

### Add-friend modal

- **N1** — Phone-shaped email → backend 400 `INVALID_IDENTIFIER` →
  field-level message about email-only.
- **N2** — Malformed email → 422 `VALIDATION_ERROR` → field error
  from `details[0].issue`.
- **N3** — Empty input → client-side Zod error before any network call.
- **N4** — Unknown email → 404 `USER_NOT_FOUND` → field error
  "couldn't find that email".
- **N5** — Already friends → 409 `CONFLICT` → field error.
- **N6** — Self-add → 422 `SELF_ADD_FORBIDDEN` → field error.
- **N7** — 6th rapid submit → 429 `RATE_LIMITED` → toast with
  retry-after.
- **N8** — 5xx → generic toast, modal stays open with the form
  preserved.

### Friend list

- **N9** — `RATE_LIMITED` on initial load → toast.
- **N10** — Network error on initial load → banner with retry.
- **N11** — List response with no email/phone fields (assert on
  rendered DOM that no `@` appears anywhere).

### Friend detail

- **N12** — 404 on balance fetch → "no longer friends" copy +
  back-link.
- **N13** — Remove confirmation cancel does not call the API.
- **N14** — Remove succeeds → list invalidates, toast appears,
  navigation back fires.
- **N15** — Remove 404 race → toast "already removed", navigate back.

### Layout / guard

- **N16** — Unauthenticated visit to `/friends` → redirect to `/login`
  (regression of the Phase 2d guard).

## Constraints

- **CLAUDE.md red-line 1** — No env-specific identifiers in source.
  No new `EXPO_PUBLIC_*` envvars.
- **CLAUDE.md red-line 2** — No new AWS resources.
- **CLAUDE.md red-line 3** — N1–N16 all ship with this PR. Coverage
  thresholds enforced in CI.
- **No bundle-budget regression** — < 350 KB gz hard, < 300 warn.

## Summary

Phase 3b ships the four-screen friends UX (list, detail, add-friend
modal, top-nav link) on top of the Phase 3a backend, all via the
generated SDK. Privacy invariants from 3a flow through unchanged:
no email, no phone, no friend lists exposed across users. Phase 4
will wire real balance numbers into the detail page and the
"settle up" CTA without re-architecting either screen.
