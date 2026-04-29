# Phase 2d — Expo Client Auth Foundation — Tasks

Six phases. Each ends with the test suite green and coverage ≥ 99% on
`lib/**` and ≥ 80% on `app/**` + `components/**`. Phases ship as a
single PR with one commit per phase (matches Phase 2a/2b/2c cadence).

---

## Phase 1 — Repo bootstrap

Goal: `pnpm install` succeeds, `pnpm --filter @contricool/client test`
runs zero tests green, `pnpm --filter @contricool/client lint` passes
on an empty source tree.

- [ ] **T1.1** Create `apps/client/package.json` with name
      `@contricool/client`, version `0.0.1`, private, scripts
      (`dev`, `dev:web`, `build:web`, `lint`, `lint:fix`, `typecheck`,
      `test`, `test:watch`, `test:coverage`), and the dependency set
      from design.md NFR1.1.
- [ ] **T1.2** Create `apps/client/app.json` (Expo config: name slug
      `contricool`, scheme `contricool`, web bundler `metro`, no
      native push permissions, splash placeholder).
- [ ] **T1.3** Create `apps/client/tsconfig.json` extending
      `expo/tsconfig.base`, `strict: true`,
      `noUncheckedIndexedAccess: true`, paths `~/*: ./*`.
- [ ] **T1.4** Create `apps/client/babel.config.js` with
      `babel-preset-expo` + `nativewind/babel`.
- [ ] **T1.5** Create `apps/client/metro.config.js` with NativeWind
      Metro plugin wiring (`withNativeWind`).
- [ ] **T1.6** Create `apps/client/tailwind.config.ts` consuming
      `lib/tokens.ts` (created Phase 2). Theme `colors`, `spacing`,
      `borderRadius`, `fontFamily` per Design 10.
- [ ] **T1.7** Create `apps/client/global.css` with the NativeWind
      `@tailwind base/components/utilities` triplet.
- [ ] **T1.8** Create `apps/client/biome.json` (2-space, single
      quotes, trailing commas — matches root project style).
- [ ] **T1.9** Create `apps/client/vitest.config.ts` per design.md
      with v8 coverage thresholds.
- [ ] **T1.10** Create `apps/client/test-setup.ts` (jest-dom, MSW
      server lifecycle, `matchMedia` stub, env stub).
- [ ] **T1.11** Create `apps/client/.env.local.example` documenting
      `EXPO_PUBLIC_API_BASE_URL`.
- [ ] **T1.12** Update root `.gitignore` to add `apps/client/.env.local`,
      `apps/client/.expo/`, `apps/client/dist/`, `apps/client/node_modules/`,
      `apps/client/coverage/`.
- [ ] **T1.13** Update root `pnpm-workspace.yaml` is **already**
      `apps/*` — no change needed; verify `pnpm install` picks up the
      new workspace.
- [ ] **T1.14** Update root `Makefile` with `client-dev`, `client-test`,
      `client-build`, `client-lint`, `client-typecheck` targets that
      shell out to `pnpm --filter @contricool/client …`.
- [ ] **T1.15** Update `.github/workflows/ci.yml` adding the `client`
      job per design.md (`pnpm install --frozen-lockfile`, lint,
      typecheck, test:coverage, build:web, bundle-size script).
- [ ] **T1.16** Add `apps/client/scripts/check-bundle-size.mjs` —
      gzips the largest JS chunk in `dist/_expo/static/js/web/`,
      fails > 300 KB, warns > 250 KB.
- [ ] **T1.17** Run `pnpm install` from repo root → no errors.
      Commit `pnpm-lock.yaml`.
- [ ] **T1.18** Run `pnpm --filter @contricool/client lint && typecheck && test`
      → all green.

## Phase 2 — Tokens + UI primitives

Goal: copy-pasted react-native-reusables primitives styled with
NativeWind tokens, with ≥ 80% coverage on `components/`.

- [ ] **T2.1** Create `apps/client/lib/tokens.ts` exporting `colors`,
      `radii`, `space`, `typography` per Design 10.
- [ ] **T2.2** Create `apps/client/lib/utils.ts` with `cn()` helper
      (clsx + tailwind-merge).
- [ ] **T2.3** Create `apps/client/components/ui/Button.tsx` — variants
      (primary/secondary/ghost/destructive) × sizes (sm/md/lg) via
      `class-variance-authority`; `loading`, `disabled` props; renders
      Spinner inline.
- [ ] **T2.4** Create `apps/client/components/ui/Input.tsx` — wraps
      `<TextInput>` with NativeWind classes, accepts
      `secureTextEntry`, `inputMode`, `aria-describedby`, `aria-invalid`.
- [ ] **T2.5** Create `apps/client/components/ui/Label.tsx` — semantic
      `<label>` (DOM via RN-Web) with `htmlFor` shim.
- [ ] **T2.6** Create `apps/client/components/ui/Card.tsx` — surface
      container with optional header/footer slots.
- [ ] **T2.7** Create `apps/client/components/ui/Spinner.tsx` — small
      and large via prop; uses `<ActivityIndicator>`.
- [ ] **T2.8** Create `apps/client/components/ui/Select.tsx` — RN-Web
      renders native `<select>`; `options` prop, RHF-friendly.
- [ ] **T2.9** Create `apps/client/components/ui/Toaster.tsx` —
      Zustand-backed toast queue with `success`/`error`/`info` API
      and a `<Toaster />` mount component reading the queue.
- [ ] **T2.10** Create `apps/client/components/ui/form.tsx` — RHF
      wrappers `<FormField>`, `<FormItem>`, `<FormLabel>`,
      `<FormControl>`, `<FormMessage>`. Uses Context to plumb field
      state to nested children. Maps server `details[]` errors via
      `setError` shim.
- [ ] **T2.11** Tests `__tests__/components/ui/Button.test.tsx` — all
      variants render; loading shows Spinner; disabled blocks press;
      accessibility (`role=button`, `aria-disabled`).
- [ ] **T2.12** Tests `__tests__/components/ui/Input.test.tsx` —
      controlled value updates; aria attributes thread through;
      error state.
- [ ] **T2.13** Tests `__tests__/components/ui/form.test.tsx` — RHF
      integration: invalid submit shows error message linked via
      `aria-describedby`.
- [ ] **T2.14** Tests `__tests__/components/ui/Toaster.test.tsx` —
      toast queue add/remove/auto-dismiss.
- [ ] **T2.15** Snapshot/render smoke for `Card`, `Spinner`, `Select`,
      `Label` (one test each).
- [ ] **T2.16** Run coverage; `components/**` ≥ 80% — green.

## Phase 3 — API client + driver + store + schemas

Goal: 99% coverage on `lib/**`. All eight backend endpoints
exercised positive + negative through the driver; auth store survives
every documented edge case.

- [ ] **T3.1** Create `apps/client/lib/types.ts` — backend contract
      types (`SignupInput`, `LoginResponse`, `RefreshResponse`,
      `ApiError`, `ResetPasswordInput`, etc.). Mirrors Phase 2c
      Pydantic shapes. Documented for replacement by the generated
      SDK in Phase 2e.
- [ ] **T3.2** Create `apps/client/lib/api.ts` per design.md:
      `apiFetch<T>` with `auth: 'bearer' | 'public'`, error envelope
      parsing, `__noRetry` recursion guard, 401-retry-once flow,
      `ApiErrorException`.
- [ ] **T3.3** Create `apps/client/lib/auth-driver.ts` — `AuthDriver`
      interface only.
- [ ] **T3.4** Create `apps/client/lib/auth-driver.web.ts` — concrete
      driver delegating to `apiFetch`. One method per backend
      endpoint.
- [ ] **T3.5** Create `apps/client/lib/id-token.ts` — `decodeIdToken(token)`
      returns `{user_id, name, currency} | null`. Base64url + JSON
      parse only; no signature verification (backend owns that).
- [ ] **T3.6** Create `apps/client/lib/auth-store.ts` — Zustand store
      per design.md. Methods delegate to driver; `refreshSession`
      uses `decodeIdToken` to populate `user`.
- [ ] **T3.7** Create `apps/client/lib/error-mapping.ts` — `mapApiError`
      helper returning the tagged-union `ScreenError`.
- [ ] **T3.8** Create `apps/client/lib/schemas.ts` — Zod schemas for
      Login / Signup / VerifyEmail / ForgotPassword / ResetPassword
      per design.md.
- [ ] **T3.9** Create `apps/client/lib/query-client.ts` — TanStack
      Query factory with sensible defaults (`staleTime: 30_000`,
      `gcTime: 5*60_000`).
- [ ] **T3.10** Create `apps/client/__tests__/msw-handlers.ts` —
      default happy-path handlers for all 8 `/v1/auth/*` endpoints.
- [ ] **T3.11** Tests `__tests__/lib/api.test.ts`:
      - Positive: bearer attached when store has token; public skips
        bearer; 204 resolves void; 200 resolves JSON.
      - Negative: 4xx with envelope → `ApiErrorException`; raw HTML
        5xx → `NETWORK_ERROR` synthesised (N20).
      - 401 retry: protected-path 401 → refresh succeeds → original
        retried once → resolves (N17).
      - 401 retry: protected-path 401 → refresh also 401 → signOut
        called → original 401 surfaced (N18).
      - Public-path 401 (e.g. `/v1/auth/login`) → no retry, surfaced
        directly (N19).
      - `__noRetry` blocks recursion.
- [ ] **T3.12** Tests `__tests__/lib/auth-driver.web.test.ts` — one
      positive per method (8 tests) hitting MSW handlers; verify
      paths + bodies.
- [ ] **T3.13** Tests `__tests__/lib/auth-store.test.ts`:
      - `signIn` populates store on success.
      - `signOut` calls driver then clears state; survives driver
        failure (N16).
      - `refreshSession` populates store on success (N14); leaves
        empty on failure (N13).
      - `loading` flag toggles correctly across all methods.
- [ ] **T3.14** Tests `__tests__/lib/id-token.test.ts` — valid token
      parses; malformed returns null; missing claims returns null.
- [ ] **T3.15** Tests `__tests__/lib/error-mapping.test.ts` —
      `INVALID_CREDENTIALS` → banner; `RATE_LIMITED` → toast with
      retryAfter; `VALIDATION_ERROR` with details → field array;
      unknown code → generic toast.
- [ ] **T3.16** Tests `__tests__/lib/schemas.test.ts` — each schema
      accepts a valid payload, rejects malformed cases (email,
      password length, currency enum, E.164 phone, password match
      refinement).
- [ ] **T3.17** Tests `__tests__/lib/storage_negative.test.ts` (N21):
      after a happy login, `localStorage.length === 0` and
      `sessionStorage.length === 0`. Asserts the entire keys array
      is empty.
- [ ] **T3.18** Tests `__tests__/lib/logging_redaction.test.ts`
      (N23, N24): spy on `console.{log,info,warn,error}`; run
      happy login + verify-email; assert no spy call argument
      stringifies any of `[email, password, code, access_token, id_token]`.
- [ ] **T3.19** Run coverage; `lib/**` ≥ 99% — green.

## Phase 4 — Public auth screens

Goal: five auth screens compose the primitives + RHF + auth store +
error mapper, with at least one positive and one negative test each.

- [ ] **T4.1** Create `apps/client/app/(auth)/_layout.tsx` — public
      guard: if `user` set, `<Redirect href="/dashboard"/>`.
- [ ] **T4.2** Create `apps/client/app/(auth)/login.tsx` per R3.
- [ ] **T4.3** Create `apps/client/app/(auth)/signup.tsx` per R4.
- [ ] **T4.4** Create `apps/client/app/(auth)/verify-email.tsx` per R5
      (reads `email` query, includes resend button with 30s cooldown).
- [ ] **T4.5** Create `apps/client/app/(auth)/forgot-password.tsx` per R6.
- [ ] **T4.6** Create `apps/client/app/(auth)/reset-password.tsx` per R7
      (reads `email` query, optional prefill).
- [ ] **T4.7** Tests `__tests__/app/login.test.tsx`:
      - Positive: submit → `signIn` called → `router.replace('/dashboard')`.
      - N1: wrong password → banner "Email or password is incorrect."
      - N2: `ACCOUNT_NOT_ACTIVE` → banner with link to verify-email.
      - N3: `RATE_LIMITED` → toast with retry-after.
- [ ] **T4.8** Tests `__tests__/app/signup.test.tsx`:
      - Positive: submit → `signUp` called → redirect to verify-email.
      - N4: confirm-mismatch → field error before network.
      - N5: `EMAIL_EXISTS` → banner with login link.
      - N6: `INVALID_PASSWORD` with details → field error.
- [ ] **T4.9** Tests `__tests__/app/verify-email.test.tsx`:
      - Positive: submit → `verifyEmail` → toast → redirect to login.
      - N7: `INVALID_CODE` → banner.
      - N8: `USER_NOT_FOUND` → banner.
      - Resend button disables for 30s after click.
- [ ] **T4.10** Tests `__tests__/app/forgot-password.test.tsx`:
      - Positive: submit → toast → redirect to reset-password.
      - N9: `RATE_LIMITED` → toast.
- [ ] **T4.11** Tests `__tests__/app/reset-password.test.tsx`:
      - Positive: submit → toast → redirect to login.
      - N10: `INVALID_CODE` → field error.
      - N11: `INVALID_PASSWORD` with details → field error.
      - N12: confirm-mismatch → client refinement.
- [ ] **T4.12** Tests `__tests__/app/auth_a11y.test.tsx` (N25): each
      auth screen renders with `<Label htmlFor>` linked inputs;
      empty submit produces aria-described error messages.
- [ ] **T4.13** Run coverage; `app/(auth)/**` ≥ 80% — green.

## Phase 5 — Authenticated stub + boot probe

Goal: hard-reload UX works end-to-end in tests; signed-in users land
on dashboard, signed-out on login.

- [ ] **T5.1** Create `apps/client/app/_layout.tsx` per design.md —
      QueryClientProvider, Toaster, `useEffect(() => refreshSession(), [])`,
      `<Stack screenOptions={{headerShown: false}} />`.
- [ ] **T5.2** Create `apps/client/app/index.tsx` — read store;
      `loading` → Spinner; signed-in → `<Redirect href="/dashboard"/>`;
      else `<Redirect href="/login"/>`.
- [ ] **T5.3** Create `apps/client/app/+not-found.tsx` — generic 404
      with link to `/`.
- [ ] **T5.4** Create `apps/client/app/(app)/_layout.tsx` — auth
      guard: if no user, `<Redirect href="/login"/>`. Renders top
      bar with `Welcome, {user.name}` + Sign-out button.
- [ ] **T5.5** Create `apps/client/app/(app)/dashboard.tsx` —
      renders `Welcome, {user.name}` and `Currency: {user.currency ?? '—'}`
      and a Sign-out button calling `authStore.signOut()`.
- [ ] **T5.6** Tests `__tests__/app/dashboard.test.tsx`:
      - Positive: renders user info; Sign-out triggers `signOut`,
        redirects to login.
      - N16: Sign-out network failure → still clears state +
        redirects + error toast.
- [ ] **T5.7** Tests `__tests__/app/boot.test.tsx`:
      - N13: hard reload, no cookie → refresh 401 → store empty →
        index redirects to /login.
      - N14: hard reload, valid cookie → refresh 200 → store
        populated → index redirects to /dashboard.
      - N15: refresh network error → store empty → graceful login
        redirect.
      - N22: hard reload after sign-out → 401 → store empty.
- [ ] **T5.8** Tests `__tests__/app/auth_guard.test.tsx`:
      - Unauthenticated visit to `/dashboard` → redirect to /login.
      - Authenticated visit to `/login` → redirect to /dashboard.
- [ ] **T5.9** Run coverage; `app/**` ≥ 80% — green.

## Phase 6 — Docs, CI verify, final pass

Goal: PR-ready. README, root README touch-up, full CI run, lint +
typecheck clean, bundle-size gate green.

- [ ] **T6.1** Write `apps/client/README.md` covering: what the app
      does, prerequisites, dev workflow modes (R14.1–R14.3), env
      vars (`EXPO_PUBLIC_API_BASE_URL` only), testing, build,
      directory tour, Phase 2e roadmap.
- [ ] **T6.2** Update root `README.md` to mention the new client
      under `apps/client/` and link to its README.
- [ ] **T6.3** Update `lefthook.yml` to run Biome on staged TS/TSX
      files in `apps/client/` (or confirm the existing config
      already covers it via glob).
- [ ] **T6.4** Run `pnpm --filter @contricool/client lint:fix`
      followed by `pnpm --filter @contricool/client lint` — clean.
- [ ] **T6.5** Run `pnpm --filter @contricool/client typecheck` — clean.
- [ ] **T6.6** Run `pnpm --filter @contricool/client test:coverage` —
      thresholds met (`lib/**` ≥ 99%, `app/**` + `components/**` ≥ 80%).
- [ ] **T6.7** Run `pnpm --filter @contricool/client build:web` —
      bundle emits to `dist/`. Run `node apps/client/scripts/check-bundle-size.mjs`
      — fits under 300 KB gz; warn at 250 KB.
- [ ] **T6.8** Manual smoke: `pnpm --filter @contricool/client dev`
      → open `http://localhost:8081` → render `/login` → render
      `/signup` (no network needed for renders).
- [ ] **T6.9** `gitleaks detect --staged` and root-level grep for
      `cloudfront\.net`, `cognito-idp\..*\.amazonaws\.com`,
      `\.execute-api\..*\.amazonaws\.com` against the new client tree
      — clean.
- [ ] **T6.10** Open PR titled
      `feat(client): Phase 2d — Expo client auth foundation (5 screens, no Amplify)`
      with the design + requirements summary in the body.
- [ ] **T6.11** Address pr-code-reviewer findings; re-run CI; merge
      after green.

## Verification (manual, post-deploy)

Phase 2d does **not** modify deploy. After merge to main, deploy.yml
runs as usual (only api/infra changes deploy; the new client builds
in CI but doesn't upload until Phase 2e).

Local manual flow against the dev environment:

- Set `apps/client/.env.local` with
  `EXPO_PUBLIC_API_BASE_URL=https://<dev-cf-domain>/v1`.
- Run `pnpm --filter @contricool/client dev`.
- Open `http://localhost:8081` in a browser.
- Sign up with a fresh email → check Cognito email → verify-email
  screen → submit code → land on /login.
- Log in → land on /dashboard. See `Welcome, <name>` + Currency.
- Click Sign out → land on /login.
- Hard reload while signed-in → land back on /dashboard (cookie path).
- Hard reload after sign-out → land on /login.
- Try wrong password → see banner.
- Try `forgot-password` → check inbox → submit reset code +
  new password → log in with new password.

If all of those work end-to-end against dev, Phase 2d's UX checkpoint
passes and the phase is shippable.
