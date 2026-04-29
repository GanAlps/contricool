# `@contricool/client` — Expo client app

The single Expo SDK 52 + React Native + RN-Web codebase that ships
ContriCool's web build today and (later) iOS/Android via EAS Build with
no source rewrite.

Phase 2d covers the **auth foundation** — five public screens (login,
signup, verify-email, forgot-password, reset-password) plus a stub
authenticated dashboard. Friends, transactions, profile, settings,
native deploys, and the full SDK come in later phases.

## Stack

- **Expo SDK 52** + Expo Router 4 (file-based routing).
- **React 18** + React Native 0.76 + React Native Web 0.19.
- **NativeWind 4** + Tailwind CSS 3 — shared styles for web + native.
- **Zustand 5** for the auth store; **TanStack Query 5** for server
  state (used in Phase 3+).
- **React Hook Form 7** + **Zod 3** for forms.
- **Vitest 2** + `@testing-library/react` + **MSW 2** for tests.
- **Biome 1.9** for lint + format.

Amplify is deliberately **not** wired in this phase; the auth store
talks to a swappable `AuthDriver` and `auth-driver.web.ts` calls our
backend directly. See `specs/phase-2d-client-auth-foundation/design.md`
for the rationale and the path to add `auth-driver.native.ts` when
native ships.

## Prerequisites

- Node 22+
- pnpm 9+
- A running ContriCool backend reachable over HTTPS (Phase 2c). Local
  development points at the deployed dev environment by default.

## Environment variables

Only one is consumed at MVP:

| Variable | Purpose |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | Base URL for backend `/v1/auth/*` calls. Trailing slash optional. Defaults to `/v1` (same-origin). |

Copy `.env.local.example` → `.env.local` and fill in the dev value
from the CloudFormation outputs of `Contricool-Dev-Web` (see
`specs/runbooks/first-deploy.md`). `.env.local` is gitignored.

## Dev workflow

Three modes:

### 1. Local UI + dev API (default)

Set `EXPO_PUBLIC_API_BASE_URL=https://<dev-cf-domain>/v1` in
`.env.local`. Then:

```bash
pnpm --filter @contricool/client dev:web
```

Open `http://localhost:8081`. The browser sends cross-origin
requests with `credentials: 'include'`. CORS on the dev API Gateway
allows the local origin (Phase 1 default; if it errors, add
`http://localhost:8081` to the API stack's allowlist).

### 2. Same-origin via reverse proxy

If you want production-shape semantics (the refresh-token cookie
attaches without CORS), proxy `/v1/*` from your dev server to the
dev CloudFront. Caddy snippet:

```
:8081 {
  reverse_proxy /v1/* https://<dev-cf-domain>
  reverse_proxy http://localhost:8082  # Expo dev server
}
```

Run Expo on `8082` (`expo start --web --port 8082`) and visit
`http://localhost:8081`.

### 3. Visual smoke

`pnpm --filter @contricool/client dev:web` then click through:
`/login` → `/signup` → `/verify-email` → `/forgot-password` →
`/reset-password`. The screens render without a backend; submitting
will hit the configured base URL.

## Testing

```bash
pnpm --filter @contricool/client test            # one-shot
pnpm --filter @contricool/client test:watch      # watch mode
pnpm --filter @contricool/client test:coverage   # full report + thresholds
```

Coverage thresholds (configured in `vitest.config.ts`):

- `lib/**` — 99% lines / functions / statements, 95% branches.
- `app/**` — 80% lines / functions / statements, 70% branches.
- `components/**` — same as `app/**`.

Tests use **Vitest + jsdom + RN-Web alias + MSW**. We don't use
`@testing-library/react-native` because RNTL ships Flow source that
Vitest can't parse — RN-Web renders to actual DOM, so DOM matchers +
`@testing-library/react` are the natural fit.

## Build

```bash
pnpm --filter @contricool/client build:web
```

Outputs to `apps/client/dist/`. The bundle-size gate runs in CI:

```bash
node apps/client/scripts/check-bundle-size.mjs
```

Warns at 300 KB gz (largest chunk), fails at 350 KB gz. (Initial 2d
estimates were ~250 KB gz; the actual bundle came in at 307 KB once
the NativeWind / `react-native-css-interop` runtime was measured.
Phase 2e will reassess once the SDK lands and we know what tree-shakes.)

## Directory tour

```
apps/client/
├── app/                       # Expo Router 4 file-based routes
│   ├── _layout.tsx            # root: providers + boot refresh probe
│   ├── index.tsx              # redirect to /login or /dashboard
│   ├── +not-found.tsx
│   ├── (auth)/                # public auth screens
│   └── (app)/                 # authenticated stub dashboard
├── components/ui/             # primitives (Button, Input, Form, …)
├── lib/
│   ├── api.ts                 # fetch wrapper + 401 retry-once
│   ├── auth-driver.ts         # interface
│   ├── auth-driver.web.ts     # web impl calling /v1/auth/*
│   ├── auth-store.ts          # Zustand store
│   ├── id-token.ts            # base64url JWT decode
│   ├── error-mapping.ts       # ApiError → ScreenError
│   ├── schemas.ts             # Zod schemas for the 5 forms
│   └── tokens.ts              # design tokens
├── __tests__/                 # mirror src layout
└── scripts/check-bundle-size.mjs
```

## What's deferred

- **Native build (iOS/Android)** — post-MVP, via EAS. The screens
  already work on RN; only EAS profiles + native `auth-driver.native.ts`
  are missing.
- **Production deploy** — Phase 1's static placeholder still serves
  prod web traffic. Phase 2e flips the deploy target to this app's
  build output.
- **OpenAPI-generated SDK** — Phase 2e replaces `lib/api.ts` and
  `lib/types.ts` with `@contricool/client-sdk`.
- **Friends, transactions, profile, settings** — Phases 3, 4, 5.
- **Push notifications, deep links, PWA install prompt, i18n,
  analytics** — all post-MVP.

## Phase 2d acceptance

- [x] 5 auth screens + stub dashboard render and submit.
- [x] 401 → refresh → retry-once flow tested end-to-end.
- [x] Tokens never persisted to localStorage / sessionStorage
  (storage-negative test asserts).
- [x] Coverage thresholds met.
- [x] Lint + typecheck clean.
- [x] No env-specific identifiers in source (red-line 1).
