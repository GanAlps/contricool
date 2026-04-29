# Phase 2d — Expo Client Auth Foundation — Requirements

## Overview

Phase 2d stands up the **Expo client** (`apps/client/`) for the first time
and ships a working set of **public auth screens** wired to the Phase 2c
backend. After 2d, a real user can — in a browser — sign up, verify their
email, log in, see a stub authenticated dashboard, log out, and recover a
forgotten password, end-to-end against the dev environment.

This phase is **web-first**. The codebase is structured so iOS/Android
ship later via EAS Build with **no rewrite**; Phase 2d explicitly does
not produce native artifacts.

What 2d does **not** ship:

- The OpenAPI document and the `@contricool/client-sdk` package — those
  land in Phase 2e once the API contract is frozen post-2c. Phase 2d
  uses a thin hand-written `lib/api.ts` (typed from a temporary local
  schema) so we can talk to `/v1/auth/*` today.
- Friends, transactions, profile UI — Phases 3, 4, 5.
- A real authenticated `(app)/` layout — Phase 2d ships a **stub
  dashboard** at `/dashboard` that displays the signed-in user's name
  and currency and a Sign-out button. Nothing more.
- Native binaries — deferred to post-MVP per EXECUTION_PLAN.
- Playwright e2e — deferred to Phase 2e (the e2e suite needs the SDK
  and runs against a deployed dev stack).

## Scope

### In scope (this phase)

- `apps/client/` — Expo SDK 52 + React 18 + React Native + React Native
  Web + Expo Router 4 + NativeWind 4 + react-native-reusables primitives
  bootstrap. Single TypeScript codebase that builds for **web** today
  and **iOS/Android** later with no source changes.
- `apps/client/app/_layout.tsx` — global root: TanStack Query client
  provider, NativeWind theme provider, global `<Toaster />`, and a
  one-shot `refreshSession()` boot probe.
- `apps/client/app/(auth)/` — five public route screens:
  - `login.tsx` — email + password → backend `POST /v1/auth/login`.
  - `signup.tsx` — email + password + name + currency picker
    + optional phone → backend `POST /v1/auth/signup`.
  - `verify-email.tsx` — email + code → backend `POST /v1/auth/verify-email`.
  - `forgot-password.tsx` — email → backend `POST /v1/auth/forgot-password`.
  - `reset-password.tsx` — email + code + new password → backend
    `POST /v1/auth/reset-password`.
- `apps/client/app/(app)/` — stub authenticated section:
  - `_layout.tsx` — auth-required guard. Redirects unauthenticated
    visitors to `/login`.
  - `dashboard.tsx` — minimal page reading `user.name`, `user.currency`
    from the auth store; Sign-out button calls `POST /v1/auth/logout`.
- `apps/client/app/index.tsx` — redirects: signed-in → `/dashboard`,
  else → `/login`.
- `apps/client/lib/api.ts` — fetch wrapper for `/v1/auth/*` endpoints
  with the **web 401 → refresh → retry-once** flow from Design 10.
  Talks to `/v1` on the same origin (CloudFront fronts both web and
  API) so the `Path=/v1/auth` refresh-token cookie attaches transparently.
- `apps/client/lib/auth-store.ts` — Zustand store: `user`,
  `accessToken`, `idToken`, `loading`, `signIn`, `signOut`, `signUp`,
  `verifyEmail`, `resendEmailCode`, `forgotPassword`, `resetPassword`,
  `refreshSession`. Calls a swappable **auth driver** (R10) for every
  network operation; tokens live in memory only.
- `apps/client/lib/auth-driver.ts` — driver interface: 8 async
  methods returning the typed response/error shapes. The store knows
  the interface; not the implementation.
- `apps/client/lib/auth-driver.web.ts` — web implementation calling
  `lib/api.ts` against `/v1/auth/*`. Picked up automatically by
  Metro's platform resolver on web. (`auth-driver.native.ts` is **not**
  written in 2d — added when native lands.)
- `apps/client/components/ui/` — copy-pasted react-native-reusables
  primitives sufficient for the auth screens: `Button`, `Input`,
  `Form` (RHF wrappers), `Label`, `Card`, `Toaster`, `Spinner`,
  `Select` (for currency).
- `apps/client/lib/tokens.ts` + `tailwind.config.ts` + `global.css` —
  design tokens from Design 10 wired into NativeWind 4.
- `apps/client/app.json` — Expo project config: name, slug, web bundler
  Metro, scheme, splash, no native push permissions.
- `apps/client/package.json` — exact dep set (see NFR1 below).
- `apps/client/tsconfig.json` — strict mode, paths alias for `~/lib`
  and `~/components`.
- `apps/client/biome.json` — Biome lint+format config (replaces
  ESLint + Prettier).
- `apps/client/vitest.config.ts` + `apps/client/test-setup.ts` — Vitest
  + `@testing-library/react-native` + jsdom + MSW for API mocking.
- Root `pnpm-workspace.yaml` already declares `apps/*`; Phase 2d adds
  `apps/client/package.json` so it becomes a real workspace.
- Root `package.json` — add `expo` CLI as a workspace devDependency
  passthrough is **not** needed; we run `pnpm --filter @contricool/client …`.
- `Makefile` — wire `client-test`, `client-dev`, `client-build`,
  `client-lint` targets.
- `.github/workflows/ci.yml` — add `client` job: `pnpm install`,
  `biome check`, `tsc --noEmit`, `vitest run --coverage`.
- `apps/client/README.md` — what the app does, dev commands, env vars
  used.

### Out of scope (later phases)

- OpenAPI emit + `@contricool/client-sdk` (Phase 2e).
- Playwright web e2e + Maestro native e2e (Phase 2e and post-MVP).
- Friends, transactions, profile, settings screens (Phases 3, 4, 5).
- Native iOS/Android builds via EAS (post-MVP).
- Web bundle deployed to S3+CloudFront for the new app shell. **Phase
  2d's deploy** is local `pnpm exec expo start --web` only; CI builds
  the bundle and runs tests but does **not** upload to S3 yet (the
  Phase 1 placeholder `static/index.html` stays live until Phase 2e
  swaps the deploy target).
- Push notifications, deep links beyond `expo-router`'s defaults,
  PWA install prompt, service worker — all post-MVP.
- i18n — defer per Design 10 open question 4.

## Functional Requirements

### R1 — Project bootstrap

- **R1.1** — `apps/client/` is an **Expo SDK 52** project initialised via
  `pnpm dlx create-expo-app@latest --template blank-typescript`, then
  modified to use Expo Router 4, NativeWind 4, and the project's
  workspace conventions.
- **R1.2** — `apps/client/package.json` declares package name
  `@contricool/client`, version `0.0.1`, private. Scripts `dev`,
  `dev:web`, `build:web`, `lint`, `lint:fix`, `typecheck`, `test`,
  `test:watch`, `test:coverage`.
- **R1.3** — `tsconfig.json` extends `expo/tsconfig.base`, sets
  `strict: true`, `noUncheckedIndexedAccess: true`, paths
  `"~/*": ["./*"]`.
- **R1.4** — Biome 1.9+ replaces ESLint + Prettier; `biome.json`
  enforces 2-space indent, single quotes, trailing commas (per
  `apps/client/biome.json` to be created).
- **R1.5** — The placeholder `apps/client/static/` from Phase 1 is
  **kept** and stays the prod-deployed web bundle; Phase 2e will
  retire it. Phase 2d only adds the new app source under
  `apps/client/app/`, `lib/`, `components/`.

### R2 — Routing & navigation (Expo Router 4)

- **R2.1** — `app/_layout.tsx` is the root layout. It mounts:
  - `<QueryClientProvider client={queryClient}>` (TanStack Query 5),
  - Amplify config block, run **once** at module scope (not in render),
  - `<Toaster />`,
  - `<Stack screenOptions={{ headerShown: false }} />`.
- **R2.2** — `app/index.tsx` is the entry redirect:
  - On mount, reads auth-store `loading` + `user`.
  - `loading=true` → show full-screen Spinner.
  - `loading=false, user=null` → `<Redirect href="/login" />`.
  - `loading=false, user!=null` → `<Redirect href="/dashboard" />`.
- **R2.3** — `app/(auth)/_layout.tsx` is the public route group.
  - If a signed-in user lands here → `<Redirect href="/dashboard" />`.
  - Else renders the children.
- **R2.4** — `app/(app)/_layout.tsx` is the authenticated guard.
  - If no user → `<Redirect href="/login" />`.
  - Else renders the children plus a minimal top bar with the user's
    name + Sign-out button.
- **R2.5** — `app/+not-found.tsx` returns a generic 404 with a link
  to `/` (Expo Router's required catch-all).

### R3 — Login screen (`/login`)

- **R3.1** — Form fields: `email` (text, required), `password`
  (password input, required). Inputs styled via NativeWind classes;
  validation via React Hook Form + Zod.
- **R3.2** — Zod schema mirrors the backend `LoginRequest`: email is
  `z.string().email().toLowerCase().trim()`; password is
  `z.string().min(1)` (the backend / Cognito enforces complexity).
- **R3.3** — Submit calls `authStore.signIn({email, password})` →
  `lib/api.ts` `POST /v1/auth/login`.
- **R3.4** — On success, the auth store stores tokens in memory + user
  object, the `rt` cookie is set by the response, the screen calls
  `router.replace('/dashboard')`.
- **R3.5** — Below-form links: "Forgot password?" → `/forgot-password`,
  "Don't have an account? Sign up" → `/signup`.
- **R3.6** — Error mapping (using stable `error.code`s from Phase 2c):
  - `INVALID_CREDENTIALS` → inline form error "Email or password is
    incorrect."
  - `ACCOUNT_NOT_ACTIVE` → "Please verify your email first." with a
    link to `/verify-email?email=<entered>`.
  - `RATE_LIMITED` → toast "Too many attempts — please try again
    in a few minutes." with `Retry-After` parsed.
  - any 5xx → toast "Something went wrong. Please try again."

### R4 — Signup screen (`/signup`)

- **R4.1** — Form fields: `email`, `password`, `confirm_password`,
  `name`, `currency` (Select: USD | INR), `phone` (optional, helper
  text "Optional. We won't verify or use this.").
- **R4.2** — Zod schema:
  - `email`: `z.string().email().toLowerCase().trim()`.
  - `password`: `z.string().min(10)` + a soft client check for
    upper/lower/digit/symbol shown as helper text (the server is the
    source of truth — surface its `INVALID_PASSWORD` field details
    on submit).
  - `confirm_password`: must equal `password` (Zod refinement).
  - `name`: `z.string().trim().min(1).max(128)`.
  - `currency`: `z.enum(['USD','INR'])`.
  - `phone`: optional; if non-empty, must match
    `^\+[1-9]\d{1,14}$` (E.164).
- **R4.3** — Submit → `authStore.signUp(payload)` → backend `POST /v1/auth/signup`.
- **R4.4** — On 202, the screen `router.replace('/verify-email?email=<email>')`.
- **R4.5** — Error mapping:
  - `EMAIL_EXISTS` → inline error "An account with this email already
    exists." + link "Log in instead?"
  - `INVALID_PASSWORD` → field-level errors from `error.details[]`.
  - `VALIDATION_ERROR` → field-level errors.
  - 5xx → toast.

### R5 — Verify email screen (`/verify-email`)

- **R5.1** — Reads `email` from the URL query params (default empty).
- **R5.2** — Form fields: `email` (prefilled from query, editable),
  `code` (numeric, length 6 — Cognito's default).
- **R5.3** — Submit → `authStore.verifyEmail({email, code})` → backend
  `POST /v1/auth/verify-email`.
- **R5.4** — On 200, toast "Email verified — please log in." and
  `router.replace('/login')`.
- **R5.5** — Below-form button "Resend code" → `authStore.resendEmailCode({email})`
  → backend `POST /v1/auth/resend-email-code`. Disabled for 30s after a
  click (client-side cooldown — server's per-identity 5/h cap is the
  hard limit).
- **R5.6** — Error mapping:
  - `INVALID_CODE` → inline "Code is wrong or expired. Try again or
    request a new one."
  - `USER_NOT_FOUND` → inline "We can't find that account."
  - `RATE_LIMITED` → toast with retry-after.

### R6 — Forgot password screen (`/forgot-password`)

- **R6.1** — Form: `email`.
- **R6.2** — Submit → `authStore.forgotPassword({email})` → backend
  `POST /v1/auth/forgot-password`.
- **R6.3** — On 202, route to `/reset-password?email=<email>` and
  toast "If the email exists, a reset code has been sent."
- **R6.4** — Error: `RATE_LIMITED` → toast with retry-after.

### R7 — Reset password screen (`/reset-password`)

- **R7.1** — Reads `email` from query string (prefilled, editable).
- **R7.2** — Form: `email`, `code` (6-digit numeric), `new_password`,
  `confirm_password`.
- **R7.3** — Submit → `authStore.resetPassword({email, code, new_password})`
  → backend `POST /v1/auth/reset-password`.
- **R7.4** — On 200 → toast "Password reset — please log in." and
  `router.replace('/login')`.
- **R7.5** — Error mapping:
  - `INVALID_CODE` → inline "Code is wrong or expired."
  - `INVALID_PASSWORD` → field-level error from details.
  - `RATE_LIMITED` → toast.

### R8 — Stub dashboard (`/dashboard`)

- **R8.1** — Authenticated route (guarded by `(app)/_layout.tsx`).
- **R8.2** — Renders `Welcome, {user.name}` and `Currency: {user.currency}`.
- **R8.3** — Sign-out button → `authStore.signOut()` → backend
  `POST /v1/auth/logout` → on 204, the auth store clears tokens, the
  guard redirects to `/login`.
- **R8.4** — On Sign-out network error: still clear local state and
  redirect (server-side state is stale at worst, the next protected
  request gets a fresh 401 → refresh → retry, which then 401s and
  forces re-login). Toast the error.

### R9 — API client (`lib/api.ts`)

- **R9.1** — Base URL: `process.env.EXPO_PUBLIC_API_BASE_URL` (e.g.
  `/v1` for same-origin via CloudFront in prod; full origin in dev
  if pointing at a different host).
- **R9.2** — Every request attaches `Authorization: Bearer <accessToken>`
  if the auth store has one (skipped on the public auth endpoints
  per their public-route status — but harmless to send).
- **R9.3** — Every response with a non-2xx body parsed as the Phase 2c
  error envelope: `{error: {code, message, request_id, details?, retry_after?}}`.
  The client returns a typed `ApiError` instance for the screen to map.
- **R9.4** — On `401` from any non-`/v1/auth/*` route:
  - Once per request, call `POST /v1/auth/refresh`.
  - On refresh success, retry the original request once with the new
    bearer.
  - On refresh failure (also 401), trigger `authStore.signOut()` and
    surface the original 401 to the caller.
- **R9.5** — The 401-retry path is **not used for the public auth
  endpoints themselves** — login/refresh/etc. surface their 401 directly.

### R10 — Auth store + driver (`lib/auth-store.ts`, `lib/auth-driver*.ts`)

- **R10.1** — `lib/auth-driver.ts` declares the driver interface:
  ```ts
  export interface AuthDriver {
    signIn(input: SignInInput): Promise<LoginResponse>;
    signOut(accessToken: string): Promise<void>;
    signUp(input: SignupInput): Promise<SignupResponse>;
    verifyEmail(input: VerifyEmailInput): Promise<void>;
    resendEmailCode(input: { email: string }): Promise<void>;
    forgotPassword(input: { email: string }): Promise<void>;
    resetPassword(input: ResetPasswordInput): Promise<void>;
    refreshSession(): Promise<RefreshResponse>;
  }
  ```
  Metro's platform resolver picks `auth-driver.web.ts` on web; native
  drivers ship with the native phase.
- **R10.2** — `lib/auth-driver.web.ts` is the web implementation —
  every method delegates to `lib/api.ts` against `/v1/auth/*`.
- **R10.3** — Zustand store wraps the driver:
  ```ts
  type AuthUser = { user_id: string; name: string; currency: 'USD' | 'INR' };
  type AuthState = {
    user: AuthUser | null;
    accessToken: string | null;
    idToken: string | null;
    loading: boolean;
    signIn: (input: { email: string; password: string }) => Promise<void>;
    signOut: () => Promise<void>;
    signUp: (input: SignupInput) => Promise<void>;
    verifyEmail: (input: { email: string; code: string }) => Promise<void>;
    resendEmailCode: (input: { email: string }) => Promise<void>;
    forgotPassword: (input: { email: string }) => Promise<void>;
    resetPassword: (input: { email: string; code: string; new_password: string }) => Promise<void>;
    refreshSession: () => Promise<void>;
  };
  ```
- **R10.4** — Tokens live **in memory only** (Zustand state, never
  written to `localStorage`, `sessionStorage`, or any persistence
  layer). The `rt` HttpOnly cookie set by Phase 2c is the **only**
  persistent auth artefact on web.
- **R10.5** — On hard reload, `refreshSession()` runs once at boot
  (from `app/_layout.tsx`) and either succeeds → store populated → user
  lands on `/dashboard`, or fails → store stays empty → user lands on
  `/login`. While running, `loading=true` and `app/index.tsx` shows a
  Spinner.
- **R10.6** — `signIn` calls the driver's `signIn(...)`, then populates
  the store with `access_token`, `id_token`, and the `user` from the
  response.
- **R10.7** — Cross-tab sign-out (one tab signs out → other tabs hear
  about it) is **deferred** to the native phase — easy retrofit via
  `BroadcastChannel` if/when needed.

### R11 — Removed (Amplify deferred to native phase)

Amplify SDK is **not** wired in Phase 2d. Justification: the web auth
flow is backend-cookie-driven (Phase 2c), which doesn't fit Amplify's
client-managed-token model. Amplify ships in the native phase, behind
`auth-driver.native.ts`, where Cognito SRP + Keychain auto-detection
earn their bundle weight. The web bundle stays Amplify-free.

### R12 — Design tokens & theming

- **R12.1** — `lib/tokens.ts` exports the colors/radii/space/typography
  objects from Design 10.
- **R12.2** — `tailwind.config.ts` consumes those tokens and feeds
  NativeWind 4's `@theme`. `global.css` is the single global style
  entry.
- **R12.3** — Light mode only at MVP; `dark:` variants compile but
  are unused.
- **R12.4** — Components use NativeWind classNames only — no inline
  styles, no `StyleSheet.create`.

### R13 — Forms

- **R13.1** — All five auth forms use `react-hook-form` + `@hookform/resolvers/zod`.
- **R13.2** — Zod schemas live in `lib/schemas.ts` next to the form they
  drive. Each schema is named `<Endpoint>Schema` (e.g. `LoginSchema`,
  `SignupSchema`).
- **R13.3** — Server-side `error.details[]` are mapped onto form fields
  via `setError(field, { type: 'server', message: issue })`.
- **R13.4** — Submit buttons disable when `formState.isSubmitting`;
  loading spinner inline on the button.

### R14 — Local dev workflow

- **R14.1** — `apps/client/.env.local.example` documents required
  vars. `apps/client/.env.local` (gitignored) holds dev values.
- **R14.2** — `pnpm --filter @contricool/client dev` starts
  `expo start --web` on port `8081`.
- **R14.3** — Local dev points `EXPO_PUBLIC_API_BASE_URL` at the
  deployed dev CloudFront domain (because we don't run the API
  locally). The browser sends requests cross-origin then; CORS on the
  API Gateway HTTP API allows the dev CloudFront origin (already
  wired in Phase 1c). For same-origin behaviour, the alternative is
  `expo start --web --proxy <cloudfront-domain>`; both options
  documented in `apps/client/README.md`.
- **R14.4** — Phase 2d **does not need** any Cognito IDs in the
  client envvars — the client talks only to our backend. The
  backend already reads pool/client IDs from SSM (Phase 2b). Native
  phase will need `EXPO_PUBLIC_USER_POOL_*` once Amplify lands; not
  now.

## Non-functional Requirements

### NFR1 — Dependency policy

- **NFR1.1** — Exact deps (no `*` ranges):
  - Runtime: `expo@~52`, `react@18.3`, `react-native@0.76`,
    `react-native-web@~0.19`, `expo-router@~4`, `nativewind@4`,
    `tailwindcss@3.4`, `zustand@^5`, `@tanstack/react-query@^5`,
    `react-hook-form@^7`, `@hookform/resolvers@^3`, `zod@^3.23`,
    `class-variance-authority@^0.7`, `clsx@^2`,
    `tailwind-merge@^2`.
  - react-native-reusables primitives are **copy-pasted** into
    `components/ui/` (per Design 10), not installed as a package.
  - Dev: `typescript@~5.6`, `@types/react`, `@biomejs/biome@^1.9`,
    `vitest@^2`, `@testing-library/react-native@^12`,
    `@testing-library/jest-dom@^6`, `jsdom@^25`, `msw@^2`,
    `@vitest/coverage-v8`.
- **NFR1.2** — `pnpm install` produces a single `pnpm-lock.yaml` at
  the repo root (workspace install). The lockfile is committed.
- **NFR1.3** — Every new dep added in Phase 2d is justified inline
  in `design.md` (per CLAUDE.md "Dependencies are deliberate").

### NFR2 — Testing

- **NFR2.1** — **Coverage floor: 99% on logic** (auth store, api
  client, schemas, error-mapper helpers); **80%+ on UI** components
  per CLAUDE.md SECTION 7.
- **NFR2.2** — Tests live in `apps/client/__tests__/` mirroring the
  source tree. Vitest configured with jsdom; RNTL renders RN
  components into the DOM via React Native Web.
- **NFR2.3** — MSW intercepts every `/v1/*` call in tests using a
  handler set that mirrors the Phase 2c contract. No real network.
- **NFR2.4** — Vitest config sets `coverage.provider: 'v8'` and
  `coverage.thresholds.lines / branches / functions / statements >= 99`
  for `lib/**` and `>= 80` for `app/**` and `components/**`.

### NFR3 — Logging & telemetry

- **NFR3.1** — No third-party telemetry / analytics SDK in 2d. No
  Sentry, no Amplitude, no Mixpanel. CloudWatch RUM is the planned
  default for client errors (Design 11) — wiring deferred to Phase 6.
- **NFR3.2** — Auth screens never log the password, code, or tokens
  to `console`. Tests assert.

### NFR4 — Bundle budget & performance

- **NFR4.1** — Initial-route web bundle ≤ 350 KB gzip (hard limit) /
  ≤ 300 KB gzip (warn). CI runs `expo export -p web` then
  `scripts/check-bundle-size.mjs`. The hard limit was raised from
  the originally-estimated 300 KB once the actual NativeWind +
  `react-native-css-interop` runtime cost was measured (307 KB at
  Phase 2d landing). Phase 2e re-tightens once the generated SDK
  lands and we know what tree-shakes.
- **NFR4.2** — Web build emits **no source maps in prod** (default
  for `expo export` non-dev). Source maps in dev only.

### NFR5 — Accessibility

- **NFR5.1** — All five auth screens pass keyboard-only navigation
  (Tab, Shift+Tab, Enter to submit). Focus rings visible.
- **NFR5.2** — Color contrast ≥ WCAG AA on all text vs background.
- **NFR5.3** — Each form input has a programmatically associated
  `<Label>`. Error messages reference inputs via `aria-describedby`.

### NFR6 — Security & privacy

- **NFR6.1** — The web client **never persists any token** anywhere.
  Access + ID tokens live in Zustand state (memory) only. The
  refresh token is never readable by JS — it lives in the
  HttpOnly `Path=/v1/auth` cookie set by Phase 2c.
- **NFR6.2** — Hard reload triggers `refreshSession()`; if the
  cookie is valid, the store re-hydrates from the refresh response.
- **NFR6.3** — `lib/api.ts` never logs request bodies, response
  bodies, or tokens to `console`. A test asserts.
- **NFR6.4** — `EXPO_PUBLIC_API_BASE_URL` is the only `EXPO_PUBLIC_*`
  envvar consumed in 2d. Values come from CI / `.env.local`;
  `.env.local` is gitignored; `gitleaks` continues to scan staged
  files.
- **NFR6.5** — Strict-Transport-Security, CSP, X-Content-Type-Options,
  Referrer-Policy headers are set by CloudFront (Phase 1) — Phase 2d
  does **not** override them. The app does not load any third-party
  script in prod (no CDN scripts, no `unpkg.com`, etc.) so the CSP
  stays strict.

### NFR7 — CI integration

- **NFR7.1** — `.github/workflows/ci.yml` adds a `client` job parallel
  to the existing api/infra/lint jobs. Steps: setup-pnpm + cache,
  `pnpm install`, `pnpm --filter @contricool/client lint`,
  `pnpm --filter @contricool/client typecheck`,
  `pnpm --filter @contricool/client test:coverage`.
- **NFR7.2** — Failing client lint, typecheck, or coverage threshold
  blocks the merge.
- **NFR7.3** — `deploy.yml` is **not** modified in 2d. The web bundle
  is **not** uploaded to S3 yet — that change ships in Phase 2e
  alongside the SDK regen and the swap-out of the Phase-1 placeholder.

## Negative-test Requirements (Red Line 3)

Every screen and the auth store get negative tests with the same
weight as positive tests. Each negative is one Vitest test function.

### Auth-flow negatives

- N1 — Login with wrong password → `error.code=INVALID_CREDENTIALS`
  → form shows "Email or password is incorrect."
- N2 — Login when account not active → form shows "Please verify
  your email first." with a link to `/verify-email?email=…`.
- N3 — Login when rate-limited → toast with `Retry-After`.
- N4 — Signup with mismatched `confirm_password` → client-side Zod
  refinement triggers field error before any network call.
- N5 — Signup duplicate email → field-level `EMAIL_EXISTS` error.
- N6 — Signup weak password → server `INVALID_PASSWORD` details
  mapped onto the password field.
- N7 — Verify-email wrong code → form shows "Code is wrong or expired."
- N8 — Verify-email unknown email → "We can't find that account."
- N9 — Forgot-password rate-limited → toast.
- N10 — Reset-password wrong code → field error.
- N11 — Reset-password weak new password → field error from details.
- N12 — Reset-password confirm-mismatch → client Zod refinement.

### Auth state / store negatives

- N13 — Hard reload with no session: `refreshSession()` returns 401
  → store stays empty, redirect lands on `/login`, no token in memory.
- N14 — Hard reload with valid session: cookie attaches, refresh
  returns 200, store populates, redirect lands on `/dashboard`.
- N15 — Network error during sign-in: store sets an error message,
  the loading flag resets, the form re-enables.
- N16 — Sign-out network failure: local state is still cleared,
  guard redirects to `/login`, error toast surfaces.

### API-client negatives

- N17 — A protected (non-`/v1/auth/*`) request returns 401 → client
  calls `/v1/auth/refresh` exactly once → on success, retries the
  original request once → on second failure, signs out.
- N18 — A protected request returns 401 → refresh also returns 401
  → client signs out and surfaces the original 401, with no infinite
  retry loop.
- N19 — `/v1/auth/login` itself returning 401 does **not** trigger
  the refresh-and-retry loop — its 401 is surfaced directly to the
  caller.
- N20 — Response with no `error` envelope (e.g., raw 5xx HTML from
  CloudFront) is mapped to `{code:'NETWORK_ERROR', request_id: null}`
  and never throws.

### Storage negatives

- N21 — After a happy-path login, `localStorage` and `sessionStorage`
  are inspected — neither contains the access token, the id token,
  the refresh token, or the email. Test asserts the entire keys
  list is auth-token-free.
- N22 — Hard reload after sign-out: `refreshSession()` returns 401
  → no token, no user re-hydrates.

### Logging negatives

- N23 — During a happy-path login, `console.log/info/warn/error` is
  spied on; **no** call argument contains the password, the access
  token, the id token, or the email. Test asserts the spy.
- N24 — During a verify-email call, the OTP code is never logged.

### Accessibility negatives (smoke-only at this phase)

- N25 — Each form input renders with its associated label visible
  and reachable; submitting an empty form produces an
  aria-describedby-linked error message on each required field.

## Constraints

- **CLAUDE.md red-line 1** — No Cognito pool IDs, app-client IDs,
  CloudFront domains, or AWS account IDs in committed source. Values
  flow via `EXPO_PUBLIC_*` envvars from CI repo variables / local
  `.env.local` only.
- **CLAUDE.md red-line 2** — No new AWS resources are deployed in 2d.
  No new pricing surface. The bundle-size budget (NFR4) is the
  client-side analogue of cost discipline.
- **CLAUDE.md red-line 3** — Negative tests N1–N25 above ship in this
  PR. Coverage thresholds enforced in CI.
- **CLAUDE.md red-line 1** (no env-specific identifiers) — Phase 2d
  consumes only `EXPO_PUBLIC_API_BASE_URL`; no Cognito pool IDs or
  client IDs are needed in the bundle (the backend handles those).
- **Email-only at MVP** — Per CONSTRAINTS.md and Design 4. The signup
  form's phone field is **optional and explicitly unverified**;
  there is **no** `/verify-phone`, no `/resend-phone-code`, no SMS
  flow anywhere in the client.
- **Single-currency-per-user** — Per CONSTRAINTS.md. Currency picker
  on signup; locked thereafter (settings UI to change it lands in a
  later phase).

## Summary

Phase 2d delivers the **first end-to-end-usable** client of ContriCool:
five auth screens + a stub dashboard, on top of an Expo + Expo Router
+ NativeWind + react-native-reusables foundation that already targets
web today and native tomorrow. Tokens stay in memory; refresh tokens
stay in the HttpOnly cookie set by Phase 2c. Amplify is **deliberately
deferred** to the native phase — its model fights our cookie-based web
flow, costs ~100 KB gz on the bundle, and adds zero value on web. The
auth store talks to a swappable `AuthDriver`; web uses
`auth-driver.web.ts` calling our backend; native will add
`auth-driver.native.ts` (likely Amplify-backed) without touching the
store or screens. OpenAPI emit + SDK regen and the production web
deploy of the new bundle are explicitly deferred to Phase 2e so this
PR stays scoped to the client foundation + auth UX.
