# Phase 3b — Friends Client UI — Tasks

Five execution phases mirroring `design.md` § "Implementation phasing".
Each phase ends with `pnpm --filter @contricool/client test`,
`tsc --noEmit`, and `biome check` all green.

## Phase 1 — Sheet + NavLink primitives

- [ ] 1.1  Add `apps/client/components/ui/Sheet.tsx`. NativeWind-styled
        modal: backdrop `Pressable` (calls `onClose`), foreground card
        with close `X`, optional title slot, body slot. Props:
        `{ open, onClose, title?, children, testID? }`. No animation
        (Phase 4). RN-Web compatible.
- [ ] 1.2  Add `apps/client/components/ui/NavLink.tsx`. Wraps
        expo-router `Link`. Adds an `active` style when
        `usePathname()` matches `to`. Props: `{ to, children, testID? }`.
- [ ] 1.3  Tests under `apps/client/__tests__/components/ui/`:
        - `Sheet.test.tsx` — open/close, backdrop click, content
          render, close button.
        - `NavLink.test.tsx` — active vs inactive style; navigation
          fires.
- [ ] 1.4  Run vitest + biome + tsc; all green.

## Phase 2 — Schema, types, and TanStack Query hooks

- [ ] 2.1  Extend `apps/client/lib/types.ts` to re-export
        `FriendItem`, `FriendBalance`, `AddFriendInput`,
        `ListFriendsResponse` from the SDK with friendly aliases.
- [ ] 2.2  Extend `apps/client/lib/schemas.ts`: add
        `AddFriendSchema = z.object({ email: z.string().trim().min(1, 'Required') })`
        with `AddFriendValues` type alias. Lenient by design — the
        backend distinguishes phone-shape (400) from malformed-email
        (422).
- [ ] 2.3  Add `apps/client/lib/queries/friends.ts`:
        - `friendsKeys = { all, list(limit), balance(userId) }`.
        - `useFriends()` — `apiClient.GET('/friends', { params: { query: { limit: 50 } } })`,
          `staleTime: 30_000`.
        - `useFriendBalance(userId)` — `apiClient.GET('/friends/{user_id}/balance', …)`,
          `staleTime: 0`, `enabled: !!userId`.
        - `useAddFriend()` — mutation; on success
          `qc.invalidateQueries({ queryKey: friendsKeys.all })`.
        - `useRemoveFriend()` — mutation; on success
          `invalidateQueries({ queryKey: friendsKeys.all })` plus
          `removeQueries({ queryKey: friendsKeys.balance(userId) })`.
- [ ] 2.4  Extend `apps/client/__tests__/msw-handlers.ts` with default
        handlers for the four `/friends/*` paths (happy-path shapes).
- [ ] 2.5  Tests under `apps/client/__tests__/lib/`:
        - `queries-friends.test.ts` — each hook: happy path + one
          error path. Use `renderHook` + `withProviders`.
- [ ] 2.6  `pnpm --filter @contricool/client test`, biome, tsc — all
        green.

## Phase 3 — Friend list page

- [ ] 3.1  Add `apps/client/app/(app)/friends/index.tsx`:
        - Renders the Add-friend CTA (top-right).
        - Loading → `Spinner`.
        - Error → banner via `mapApiError` + retry button (refetch).
        - Empty → empty card + "Add friend" CTA.
        - Populated → vertical list, sorted alphabetically by `name`
          (case-insensitive). Each row tappable →
          `router.push(/friends/[userId])`.
        - Local UI state for the modal `open` boolean.
- [ ] 3.2  Tests `apps/client/__tests__/app/friends/list.test.tsx`:
        - Loading state.
        - Empty state copy + CTA.
        - Populated rows + tap → router.push fires.
        - **N9** rate-limited initial load → toast.
        - **N10** network error initial load → banner + retry.
        - **N11** rendered DOM contains no `@` (no email leak).
- [ ] 3.3  Run tests + biome + tsc.

## Phase 4 — Add-friend modal

- [ ] 4.1  Add `apps/client/components/friends/AddFriendSheet.tsx`:
        - Wraps `Sheet`. RHF + Zod with `AddFriendSchema`.
        - Submit calls `useAddFriend()`.
        - On success: close + toast `Added <name>`.
        - Per-error mapping (see design.md § "Error → field-message
          map"): `INVALID_IDENTIFIER` / `USER_NOT_FOUND` /
          `CONFLICT` / `SELF_ADD_FORBIDDEN` / `VALIDATION_ERROR`
          → `setError('email', …)`.
          `RATE_LIMITED` / 5xx → toast (modal stays open).
        - Add a `lib/error-mapping.ts` helper if needed (extend the
          existing centralised map).
- [ ] 4.2  Tests `apps/client/__tests__/app/friends/add-friend-sheet.test.tsx`:
        - **N1** phone → field "email-only" copy.
        - **N2** malformed → field error from backend `details[0].issue`.
        - **N3** empty input → client-side Zod error, no network.
        - **N4** unknown email → field "couldn't find" copy.
        - **N5** already friends → field copy.
        - **N6** self-add → field copy.
        - **N7** rate-limit → toast with retry-after, modal stays open.
        - **N8** 5xx → generic toast, modal preserved.
        - happy-path success → close + toast, list query invalidated.
- [ ] 4.3  Run tests + biome + tsc.

## Phase 5 — Friend detail page + nav + final pass

- [ ] 5.1  Add `apps/client/app/(app)/friends/[userId].tsx`:
        - `useLocalSearchParams<{ userId: string }>()`.
        - `useFriends()` cache lookup for `name` + `currency`
          (fallback to "—" when cache cold).
        - `useFriendBalance(userId)` — render Settled card with
          zeros, `last_transaction_at: '—'`.
        - "Settle up" disabled (coming-soon badge).
        - "Remove friend" → confirm dialog → `useRemoveFriend()`.
        - On remove success: toast + `router.back()`.
        - 404 on balance → "no longer friends" + back link.
- [ ] 5.2  Update `apps/client/app/(app)/_layout.tsx` to wrap routes
        in a top-bar with `NavLink` Dashboard / Friends + Sign-out.
        Keep the existing redirect-on-no-user behaviour.
- [ ] 5.3  Tests:
        - `apps/client/__tests__/app/friends/detail.test.tsx`:
          - Renders name + currency + Settled balance.
          - **N12** balance 404 → "no longer friends" + back link.
          - **N13** remove cancel → no API call.
          - **N14** remove succeeds → toast + router.back + cache
            invalidated.
          - **N15** remove 404 race → "already removed" toast +
            back.
        - `apps/client/__tests__/app/friends/nav.test.tsx`:
          - Top-bar shows both links + sign-out.
          - Active link highlighted on each route.
          - **N16** unauth visit to `/friends` → redirect to `/login`
            (regression of Phase 2d guard).
- [ ] 5.4  Update `apps/client/README.md` with the new routes.
- [ ] 5.5  Final `pnpm --filter @contricool/client test --coverage`
        ensures coverage thresholds hold (`lib/**` 99%/95%, `app/**`
        80%/70%, `components/**` 80%/70%).
- [ ] 5.6  `git push -u origin feat/phase-3b-friends-client` + open
        PR titled `feat(client): Phase 3b — friends UI`.
