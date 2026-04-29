# Phase 2e — OpenAPI + Client SDK + Production Deploy — Requirements

## Overview

Phase 2e closes the Phase 2 chapter by replacing the Phase 2d hand-rolled
client API + types with a **generated, schema-anchored TypeScript SDK**,
flipping the **production web deploy** from the Phase-1 placeholder to
the real Expo client bundle, and adding the local-dev CORS allowance
that 2d's manual test surfaced.

After 2e, a real user can hit `https://<dev-cf-domain>/` (or prod once
approved) in a browser and use the full auth flow without the dev
running anything locally; the FastAPI request/response shapes are the
single source of truth for all client types; and the auth-screen tests
keep passing through the swap.

## Scope

### In scope (this phase)

- **OpenAPI emit** — `apps/api` exports its FastAPI schema to
  `packages/openapi/openapi.yaml` (committed). A new
  `apps/api/scripts/emit_openapi.py` walks `app.main:app`, calls
  `app.openapi()`, and writes the YAML.
- **OpenAPI drift check** — `make openapi-check` regenerates and
  diffs against the committed file. CI runs it on every PR; a drift
  fails the build. Replaces the Phase-1 placeholder no-op step.
- **TypeScript SDK** — `packages/client-sdk/` becomes a real
  workspace package generated from `packages/openapi/openapi.yaml`:
  - `openapi-typescript@^7` produces `src/schema.d.ts` (types).
  - `openapi-fetch@^0.13` is the small, type-safe runtime client.
  - Re-exports a typed `ApiError` and `ApiErrorException` matching
    the Phase 2c envelope.
  - Exports a small `createClient({ baseUrl, getAccessToken,
    onUnauthenticated })` factory the Expo client wires up.
- **Client swap** — `apps/client/lib/api.ts` and `lib/types.ts` are
  replaced with thin wrappers around `@contricool/client-sdk`:
  - 401-refresh-retry-once flow lives behind the SDK factory's
    `onUnauthenticated` hook (regression-tested via N17–N20 from 2d).
  - `auth-driver.web.ts` now calls SDK methods (`client.POST('/auth/login', …)`)
    instead of `apiFetch('/auth/login', …)`.
  - Schema types replace the hand-typed shapes in `lib/types.ts`;
    that file is reduced to platform aliases (`Currency`, `AuthUser`)
    derived from the SDK schema.
- **CORS allowlist for local dev** — `apps/infra/stacks/api_stack.py`
  `cors_preflight` adds `http://localhost:8081` and `http://localhost:19006`
  to `allow_origins`, with `allow_credentials=True`. Synth test
  asserts both origins + the credentials flag. Unblocks `pnpm dev:web`
  against the dev API per `apps/client/README.md` mode 1.
- **Production web deploy flip** — `apps/infra/stacks/web_stack.py`
  switches its `BucketDeployment` source from `../client/static` to
  `../client/dist`. The Phase-1 placeholder is removed (`apps/client/static/`
  deleted; Phase 2+ owns the bundle).
- **Deploy workflow update** — `.github/workflows/deploy.yml` adds a
  `pnpm --filter @contricool/client build:web` step **before** the CDK
  deploy so `BucketDeployment` has the artefacts to upload. Smoke
  step now hits `https://<dev-cf-domain>/` and asserts 200 + the SPA
  shell loads (response body contains the bundle's main script tag),
  not just `/v1/health`.
- **CloudFront invalidation** — explicit `distribution_paths=["/*"]`
  on `BucketDeployment` so each deploy busts the SPA HTML cache.
  Static assets (`/assets/*`, `/_expo/*`) are content-addressed and
  long-cached by CloudFront's default response-headers policy.
- **CSP review** — confirm CloudFront's `response_headers_policy`
  CSP `script-src` permits the bundle's emitted scripts (same origin
  is fine; verify nothing else is loaded). No third-party scripts
  introduced.
- **Tests** — keep the 140 Phase 2d tests green. Add ~10 SDK-layer
  tests + 1 synth test for CORS + 1 synth test for the web stack
  source path. Coverage thresholds stay at the same levels.
- **Documentation** — `apps/client/README.md`, `apps/api/README.md`,
  `packages/client-sdk/README.md`, and root `README.md` updated.
  `Makefile` `openapi` and `openapi-check` targets become real.

### Out of scope (later phases)

- **Playwright web e2e against deployed dev** — captured separately;
  the install + browser-binary download alone is non-trivial and the
  test surface is small until friends/transactions land. Nightly
  Playwright run is a Phase 3 deliverable.
- **Maestro native e2e** — post-MVP, paired with EAS native builds.
- **`contricool.com` custom domain** — Phase 7+ (registrar + ACM in
  us-east-1 + Route 53 + CloudFront cert wiring).
- **CloudWatch RUM** — Phase 6 observability.
- **PWA / service worker / manifest tuning** — post-MVP per Design 10
  open question 3.
- **Phase 2c-followup idempotency** — separate small PR per
  `specs/EXECUTION_PLAN.md`.
- **Friends, transactions, profile screens** — Phases 3, 4, 5.

## Functional Requirements

### R1 — OpenAPI emit (`apps/api/scripts/emit_openapi.py`)

- **R1.1** — A standalone Python script imports `app.main:app`,
  calls `app.openapi()`, and writes the result as YAML to
  `packages/openapi/openapi.yaml`.
- **R1.2** — Sets `CONTRICOOL_SKIP_COLD_START_CONFIG=1` first so the
  emit doesn't try to fetch SSM parameters.
- **R1.3** — Pretty-prints with 2-space indent, sorted keys for
  stable diffs.
- **R1.4** — `info.version` equals `apps/api/pyproject.toml` `version`
  field. `servers` lists are removed from the export so the YAML is
  origin-neutral.
- **R1.5** — Adds an explicit `info.description` referencing
  Phase 2c (`/v1/auth/*` only at MVP).

### R2 — OpenAPI drift check (`make openapi-check`)

- **R2.1** — `make openapi` regenerates the YAML and the SDK schema.
- **R2.2** — `make openapi-check` regenerates **into a tempfile** and
  diffs against the committed `packages/openapi/openapi.yaml`.
  Non-zero diff → exit 1 with a diff snippet on stderr.
- **R2.3** — CI runs `make openapi-check` in the `openapi-check` job
  (replaces the Phase-1 placeholder echo).
- **R2.4** — Lefthook pre-commit hook runs `make openapi` (not the
  check) when files under `apps/api/app/features/**` or
  `apps/api/app/main.py` are staged, automatically restaging the
  regenerated YAML.

### R3 — Client SDK package (`packages/client-sdk/`)

- **R3.1** — `package.json` declares `@contricool/client-sdk`,
  version `0.0.1`, private, type `module`. Scripts: `generate`
  (runs `openapi-typescript`), `clean`, `build` (= `clean &&
  generate`).
- **R3.2** — Build inputs: `../openapi/openapi.yaml`. Build outputs:
  `src/schema.d.ts` (committed), `src/index.ts` (hand-written
  factory).
- **R3.3** — `src/index.ts` exports:
  - `type paths` (re-export from `schema.d.ts`).
  - `type ApiError`, `class ApiErrorException` — matching the
    Phase 2c envelope shape.
  - `function createClient(opts: ClientOptions): ContricoolClient`.
  - `type ContricoolClient = ReturnType<typeof createClient>`.
- **R3.4** — `ClientOptions` shape:
  ```ts
  type ClientOptions = {
    baseUrl: string;
    getAccessToken: () => string | null;
    onUnauthenticated: () => Promise<void>;  // called when refresh-retry fails
    onTokenRefreshed?: (tokens: { access_token: string; id_token: string }) => void;
  };
  ```
- **R3.5** — Internally wraps `openapi-fetch` with a `Middleware`
  array implementing:
  - Bearer attach (skipped when path starts with `/auth/`).
  - Error-envelope parsing → `ApiErrorException`.
  - 401-retry-once: when a non-`/auth/` request returns 401, call
    `POST /auth/refresh`, on success call `onTokenRefreshed`, retry
    the original once; on failure call `onUnauthenticated` and
    surface the 401.
- **R3.6** — Recursion guard: the refresh call itself sets a private
  flag on its `Request` so the middleware doesn't loop.
- **R3.7** — Exports `paths['/auth/login']['post']['responses']['200']['content']['application/json']`-style
  helpers under nicer names (`SignInResponse`, `SignupResponse`, …)
  so screen code stays readable.

### R4 — Expo client swap (`apps/client/`)

- **R4.1** — Add `@contricool/client-sdk` as a workspace dependency
  in `apps/client/package.json`.
- **R4.2** — `apps/client/lib/api.ts` is reduced to a singleton
  factory call:
  ```ts
  import { createClient } from '@contricool/client-sdk';
  import { useAuthStore } from './auth-store';

  export const apiClient = createClient({
    baseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? '/v1',
    getAccessToken: () => useAuthStore.getState().accessToken,
    onUnauthenticated: () => useAuthStore.getState().signOut(),
    onTokenRefreshed: ({ access_token, id_token }) =>
      useAuthStore.getState()._setTokensFromRefresh(access_token, id_token),
  });
  ```
- **R4.3** — `apps/client/lib/types.ts` exports re-named SDK aliases
  only (`AuthUser`, `Currency`, `LoginResponse`, etc.). The hand-rolled
  shapes from 2d are deleted.
- **R4.4** — `apps/client/lib/auth-driver.web.ts` calls
  `apiClient.POST('/auth/login', { body: input })` etc. instead of
  `apiFetch('/auth/login', …)`.
- **R4.5** — `apps/client/lib/auth-store.ts` adds
  `_setTokensFromRefresh(access, id)` — the SDK calls this from its
  middleware so the store stays the source of truth for tokens.
  Existing `setApiAuthAccessors` wiring is removed; the SDK factory
  closes over the store directly.
- **R4.6** — All Phase 2d screens (login/signup/verify-email/forgot/reset/dashboard)
  continue to compile and pass tests with **zero diff** beyond
  imports — proves the swap was contract-preserving.

### R5 — CORS allowlist for local dev

- **R5.1** — `api_stack.py` `cors_preflight` becomes:
  ```python
  cors_preflight=apigwv2.CorsPreflightOptions(
      allow_methods=[apigwv2.CorsHttpMethod.POST,
                     apigwv2.CorsHttpMethod.GET,
                     apigwv2.CorsHttpMethod.OPTIONS],
      allow_origins=[
          # Same-origin via CloudFront in production.
          f"https://{cloudfront_domain}",
          # Local Expo dev server (and Caddy proxy alt).
          "http://localhost:8081",
          "http://localhost:8082",
          "http://localhost:19006",
      ],
      allow_headers=[…],
      allow_credentials=True,
      expose_headers=["x-request-id", "retry-after"],
      max_age=Duration.minutes(10),
  )
  ```
- **R5.2** — `cloudfront_domain` is passed from `app.py` (read from
  the Web stack output via `Fn.import_value` on a deferred export, or
  a stack-level constructor param).
- **R5.3** — The wildcard `allow_origins=["*"]` from Phase 1 is
  replaced — `allow_credentials=True` requires a strict origin list
  per CORS spec.
- **R5.4** — Synth test asserts both `localhost` origins are present,
  the production CloudFront origin is present, and credentials are
  enabled.

### R6 — Production web deploy flip

- **R6.1** — `web_stack.py` `BucketDeployment` `sources` switches
  from `s3_deployment.Source.asset("../client/static")` to
  `s3_deployment.Source.asset("../client/dist")`.
- **R6.2** — `apps/client/static/` is deleted. The `index.html`
  placeholder is no longer the prod web bundle.
- **R6.3** — `BucketDeployment` invalidates `/*` on every deploy
  (the Expo build emits content-hashed asset filenames so over-broad
  invalidation has no real cost).
- **R6.4** — `BucketDeployment` `cache_control` is removed (or set
  per-file: `index.html` short-cache, hashed assets long-cache).
  Default Expo bundle structure: `dist/index.html` (no hash) +
  `dist/_expo/static/js/web/<hash>.js` + `dist/assets/<hash>` —
  the per-file approach uses two `Source.asset` invocations with
  different `cache_control_max_age`, but the simpler "invalidate
  everything" approach is fine at MVP scale.
- **R6.5** — Synth test asserts the bundle source path is
  `../client/dist`, not `../client/static`.

### R7 — Deploy workflow update

- **R7.1** — `.github/workflows/deploy.yml` adds, before the
  `cdk deploy` step:
  ```yaml
  - uses: pnpm/action-setup@v4
  - uses: actions/setup-node@v4
    with: { node-version: "22", cache: "pnpm" }
  - run: pnpm install --frozen-lockfile
  - run: pnpm --filter @contricool/client-sdk build  # generate types
  - run: pnpm --filter @contricool/client build:web
  ```
  This pre-builds `apps/client/dist/` so `BucketDeployment` has
  artefacts.
- **R7.2** — A new check verifies `apps/client/dist/index.html`
  exists; missing artefacts → fail before CDK deploy.
- **R7.3** — Smoke step is upgraded:
  - `curl https://${CF_DOMAIN}/v1/health` → 200 (existing).
  - **New**: `curl https://${CF_DOMAIN}/` → 200 + body contains
    `<div id="root"`-style hook + a `<script src=` tag — proves the
    SPA shell is served, not the Phase-1 placeholder.
- **R7.4** — Bundle-size gate from Phase 2d (`scripts/check-bundle-size.mjs`)
  runs after the build step here too.

### R8 — Documentation

- **R8.1** — `apps/client/README.md` updated: removes the "Phase 2d
  doesn't deploy" caveat; adds the `pnpm dlx @contricool/client-sdk`
  workflow note; updates deploy section to describe the dist→S3 flow.
- **R8.2** — `apps/api/README.md` (or new `apps/api/scripts/README.md`)
  documents `emit_openapi.py` and `make openapi`.
- **R8.3** — `packages/client-sdk/README.md` covers the package's
  public API (createClient, types) and how to regenerate.
- **R8.4** — Root `README.md`: layout diagram updated; phase status
  bumped.
- **R8.5** — `specs/EXECUTION_PLAN.md` Phase 2 row marked complete.

## Non-functional Requirements

### NFR1 — Dependency policy

- **NFR1.1** — New deps:
  - `apps/api`: `pyyaml@^6` (dev) for the emit script.
  - `packages/client-sdk`:
    - `openapi-typescript@^7` (dev only — generates types).
    - `openapi-fetch@^0.13` (runtime).
  - `apps/client`: `@contricool/client-sdk` (workspace).
- **NFR1.2** — Removed deps from `apps/client`: nothing yet — the
  hand-rolled `lib/api.ts` and `lib/types.ts` shrink in place but
  no `package.json` entries change.

### NFR2 — Testing

- **NFR2.1** — All 140 Phase 2d tests stay green. Adjust mocks where
  the SDK swap changes call shapes; **no test deletion**.
- **NFR2.2** — `packages/client-sdk` gets its own `vitest` suite:
  - createClient happy path (mocked fetch).
  - 401-retry-once flow with refresh succeed → retry succeeds.
  - 401-retry-once with refresh-also-fail → onUnauthenticated called,
    original 401 surfaced.
  - `/auth/*` 401 not retried.
  - Envelope parsing: 4xx with envelope, 5xx without, network error.
- **NFR2.3** — Coverage thresholds for `packages/client-sdk/src/**`:
  99% lines/funcs/stmts, 95% branches.
- **NFR2.4** — Synth tests in `apps/infra/tests/test_synth.py` add:
  - CORS contains the three localhost origins + production origin
    + credentials flag.
  - Web stack `BucketDeployment` source path equals
    `../client/dist`.

### NFR3 — Security

- **NFR3.1** — CORS `allow_credentials=True` requires an explicit
  origin list (no `*`) per CORS spec — already addressed in R5.
- **NFR3.2** — The SDK's middleware never logs tokens or bodies to
  `console`. Tests assert.
- **NFR3.3** — `allow_headers` stays minimal; no wildcards.

### NFR4 — Deploy reliability

- **NFR4.1** — The deploy workflow's web-build step is the **same
  command** CI uses to verify the bundle in `ci.yml`'s `client` job.
  Drift between CI build and deploy build is impossible.
- **NFR4.2** — A failed bundle build fails the deploy before any
  CDK changes apply (CDK runs after the build step).

### NFR5 — Documentation freshness

- **NFR5.1** — Every new dep in NFR1.1 is justified inline in
  `design.md` per CLAUDE.md "Dependencies are deliberate".

## Negative-test Requirements (Red Line 3)

### OpenAPI / SDK negatives

- **N1** — `make openapi-check` against an out-of-sync committed YAML
  exits non-zero with a diff (`tests/test_openapi_drift.py`).
- **N2** — SDK's `apiClient.POST('/auth/login')` against a 401
  response throws `ApiErrorException` with `code=INVALID_CREDENTIALS`.
- **N3** — SDK 401 on a non-`/auth` route triggers exactly one refresh
  call, then exactly one retry; on second 401 calls `onUnauthenticated`
  and surfaces the original 401 with no infinite loop.
- **N4** — SDK 401 on `/auth/login` does **not** trigger refresh-retry
  (regression of N19 from Phase 2d).
- **N5** — SDK on a raw 5xx HTML response synthesises
  `code='NETWORK_ERROR'`.

### Client store negatives (regression-only)

- **N6** — Phase 2d N17–N20 (api.ts retry behaviours) still pass with
  the SDK in place.
- **N7** — Phase 2d N21 (no localStorage / sessionStorage writes) still
  passes.
- **N8** — Phase 2d N23/N24 (no token / OTP code in console.log) still
  pass with the SDK in place.

### CORS / synth negatives

- **N9** — Synth: API Gateway `cors_preflight.allow_origins` does
  **not** contain `*` when `allow_credentials=True`.
- **N10** — Synth: Web stack `BucketDeployment` does **not** still
  reference `../client/static`.

### Deploy negatives (manual, in deploy.yml)

- **N11** — Deploy workflow fails fast if `apps/client/dist/index.html`
  is missing after the build step.
- **N12** — Smoke step asserts the served `/` body contains a
  `<script src=` tag (proves bundle shell, not placeholder).

## Constraints

- **CLAUDE.md red-line 1** — No env-specific identifiers in source.
  CORS allow-origin lists production CloudFront via runtime CDK
  binding (not a string literal); `allow_origins` for localhost is
  fine in source (not env-specific).
- **CLAUDE.md red-line 2** — No new always-on AWS resources. The
  `BucketDeployment` source change adds zero cost (same bucket).
- **CLAUDE.md red-line 3** — N1–N12 above ship in this PR; coverage
  thresholds enforced.
- **No new build-time secrets** — SDK generation is deterministic;
  inputs are already source-controlled.
- **Backward compatibility** — Web bundle URL stays the same
  (`https://<dev-cf-domain>/`); we replace the **content** at that URL.
  No client-facing breaking change because Phase 1 had no real users.

## Summary

Phase 2e is the **final 2-chapter cleanup**: ship the OpenAPI →
TypeScript SDK pipeline that makes the FastAPI shapes the single
source of truth across the stack; replace the Phase 2d hand-rolled
client API with the generated SDK behind the same store/driver
contract; flip the production web deploy from the Phase-1 placeholder
to the real Expo bundle; and add the local-dev CORS allowance that
Phase 2d's manual test surfaced. After 2e, dev and prod CloudFront
URLs serve the working auth flow end-to-end without any local
running, and Phases 3+ build features against a typed, drift-checked
contract.
