# Phase 2e — OpenAPI + Client SDK + Production Deploy — Tasks

Five implementation phases, each ends with green tests + lint clean.
Phases ship as a single PR (matches Phase 2a/2b/2c/2d cadence).

---

## Phase 1 — OpenAPI emit + drift check

Goal: `make openapi` produces a committed `packages/openapi/openapi.yaml`,
`make openapi-check` is wired into CI and rejects drift.

- [ ] **T1.1** Add `pyyaml@^6` to `apps/api/pyproject.toml` `[project.optional-dependencies].dev`.
- [ ] **T1.2** Create `apps/api/scripts/emit_openapi.py` per design.md.
- [ ] **T1.3** Update root `Makefile`:
      - `openapi` target invokes the emit script (Python from
        `master-venv`) and `pnpm --filter @contricool/client-sdk build`.
      - `openapi-check` target invokes the script with `--check`.
- [ ] **T1.4** Run `make openapi` once to populate
      `packages/openapi/openapi.yaml`. Commit the result.
- [ ] **T1.5** Update `.github/workflows/ci.yml` `openapi-check` job:
      checkout, setup Python 3.12, install `apps/api[dev]`, `make openapi-check`.
- [ ] **T1.6** Update `lefthook.yml` to add a pre-commit hook that
      re-runs `make openapi` when files under
      `apps/api/app/features/**/*.py` or `apps/api/app/main.py` are
      staged, then `git add`s the regenerated outputs.
- [ ] **T1.7** Verify locally: edit a model field name, run
      `make openapi-check` → exits 1 with diff; revert; re-run → 0.

## Phase 2 — Client SDK package

Goal: `packages/client-sdk/` is a real workspace with 99% coverage on
`src/**`.

- [ ] **T2.1** Create `packages/client-sdk/package.json` per design.md
      with `openapi-fetch` as dep and `openapi-typescript` + `vitest`
      + `@vitest/coverage-v8` + `typescript` as dev deps.
- [ ] **T2.2** Create `packages/client-sdk/tsconfig.json` (strict,
      bundler resolution, no emit).
- [ ] **T2.3** Run `pnpm install` from the repo root to add the new
      workspace package.
- [ ] **T2.4** Run `pnpm --filter @contricool/client-sdk generate`
      (or `pnpm --filter @contricool/client-sdk build`) — produces
      `src/schema.d.ts`. **Commit the file** (it's generated but
      stable; the drift check guarantees freshness).
- [ ] **T2.5** Implement `src/errors.ts` per design.md: `ApiError`,
      `ApiErrorException`.
- [ ] **T2.6** Implement `src/middleware.ts` per design.md:
      `authMiddleware(client, opts)` with bearer-attach, envelope-parse,
      and 401-retry-once (with private `RETRY_FLAG` recursion guard).
- [ ] **T2.7** Implement `src/index.ts` per design.md: `createClient`,
      friendly response-type aliases, `paths` re-export.
- [ ] **T2.8** Create `packages/client-sdk/vitest.config.ts` (jsdom,
      v8 coverage, thresholds 99/95).
- [ ] **T2.9** Create `packages/client-sdk/src/__tests__/createClient.test.ts`:
      one happy-path test through the full middleware stack.
- [ ] **T2.10** Create `src/__tests__/middleware.test.ts` covering:
      - Bearer attach on non-/auth/ when token present.
      - Bearer skip on /auth/ even with token present.
      - 401 retry success path (refresh ok → tokens updated → original
        retried with new bearer → returns data).
      - 401 retry-then-signout path (refresh 401 → onUnauthenticated
        called → original 401 thrown).
      - No retry on /auth/login 401.
      - Recursion guard: refresh response itself doesn't loop.
- [ ] **T2.11** Create `src/__tests__/errors.test.ts` covering:
      - Phase 2c envelope → `ApiErrorException`.
      - Raw HTML 5xx → `code='NETWORK_ERROR'`.
      - Empty 5xx → `code='NETWORK_ERROR'`.
      - Missing `request_id` → `null`.
- [ ] **T2.12** Run `pnpm --filter @contricool/client-sdk test:coverage`
      — 99% lines/funcs/stmts, 95% branches green.

## Phase 3 — Expo client swap

Goal: replace the hand-rolled `lib/api.ts` + `lib/types.ts` with thin
SDK wrappers; all 140 Phase 2d tests stay green.

- [ ] **T3.1** Add `@contricool/client-sdk: workspace:*` to
      `apps/client/package.json` `dependencies`.
- [ ] **T3.2** Add `_setTokensFromRefresh(accessToken, idToken)`
      action to `apps/client/lib/auth-store.ts`. Remove the
      `setApiAuthAccessors(...)` block at module bottom.
- [ ] **T3.3** Replace `apps/client/lib/api.ts` with the singleton
      `apiClient = createClient({...})` factory call per design.md.
      Re-export `ApiError`, `ApiErrorException` from the SDK.
- [ ] **T3.4** Replace `apps/client/lib/types.ts` with renamed SDK
      aliases per design.md.
- [ ] **T3.5** Update `apps/client/lib/auth-driver.web.ts` to call
      `apiClient.POST('/auth/...', { body: input })` instead of
      `apiFetch('/auth/...', ...)`. Map `r.data!` to the driver's
      return shape.
- [ ] **T3.6** Run `pnpm --filter @contricool/client typecheck` —
      iterate until clean.
- [ ] **T3.7** Run `pnpm --filter @contricool/client test`:
      - `__tests__/lib/api.test.ts`: replace its old `setApiAuthAccessors`
        plumbing with calls through `apiClient`. Same scenarios; new
        invocation shape.
      - `__tests__/lib/auth-driver.web.test.ts`: assertions adjust for
        the SDK call shape; logic unchanged.
      - `__tests__/lib/auth-store.test.ts`: 401-retry integration test
        uses the new `_setTokensFromRefresh` action.
      - All other 130+ tests: zero diff expected. Iterate fixes only
        on the three files above.
- [ ] **T3.8** Run `pnpm --filter @contricool/client test:coverage` —
      thresholds (lib 99/95, app 80/70, components 80/70) all green.
- [ ] **T3.9** Run `pnpm --filter @contricool/client lint` — clean.

## Phase 4 — CORS + WebStack flip + synth tests

Goal: API CORS allows local-dev origins with credentials; web stack
serves the Expo bundle, not the placeholder.

- [ ] **T4.1** Update `apps/infra/stacks/api_stack.py`
      `cors_preflight` per design.md:
      - explicit `allow_methods` (POST, GET, OPTIONS).
      - `allow_origins` = production CF (read from SSM via
        `ssm.StringParameter.value_for_string_parameter`) + the three
        localhost origins.
      - `allow_credentials=True`.
      - `expose_headers=['x-request-id', 'retry-after']`.
- [ ] **T4.2** Add `cloudfront_domain_param_name: str` constructor
      kwarg to `ApiStack` (default `f"/contricool/{env}/cloudfront-domain"`).
- [ ] **T4.3** Update `apps/infra/app.py` to pass the SSM param name
      to `ApiStack` for both dev and prod envs.
- [ ] **T4.4** Update `apps/infra/stacks/web_stack.py` `BucketDeployment`:
      `sources=[s3_deployment.Source.asset("../client/dist")]`,
      `distribution_paths=["/*"]`, cache-control 5-min default.
- [ ] **T4.5** `git rm -r apps/client/static/`. Update
      `apps/client/README.md` and `web_stack.py` comments.
- [ ] **T4.6** Add synth test
      `test_api_stack_phase2e_cors_credentials_with_strict_origins`
      asserting all three localhost origins, no `*`, and
      `AllowCredentials: true`.
- [ ] **T4.7** Add synth test
      `test_web_stack_phase2e_serves_dist_not_static` asserting the
      bundle deployment source asset is the dist path.
- [ ] **T4.8** Update `apps/infra/README.md` documenting the
      first-deploy SSM-empty CORS behaviour.
- [ ] **T4.9** Run `cd apps/infra && pytest` — green.
      Run `cd apps/infra && cdk synth Contricool-Dev-Api Contricool-Dev-Web > /dev/null` — clean.

## Phase 5 — Deploy workflow + docs + final pass

Goal: PR-ready. Deploy workflow pre-builds the bundle; smoke step
asserts the SPA shell; docs are fresh.

- [ ] **T5.1** Update `.github/workflows/deploy.yml`:
      - Before each `cdk deploy` step, add: `pnpm/action-setup`,
        `setup-node`, `pnpm install --frozen-lockfile`,
        `pnpm --filter @contricool/client-sdk build`,
        `pnpm --filter @contricool/client build:web`.
      - Verify-bundle step: `test -f apps/client/dist/index.html`.
      - Bundle-size gate: `node apps/client/scripts/check-bundle-size.mjs`.
- [ ] **T5.2** Update `deploy.yml` smoke steps (dev + prod) to add a
      curl on `/` and grep for `<script` per design.md.
- [ ] **T5.3** Update `apps/client/README.md`:
      - Remove "Phase 2d doesn't deploy" caveat.
      - Add SDK regen workflow note.
      - Update deploy section to describe dist→S3 flow.
      - Note that `apps/client/static/` is removed.
- [ ] **T5.4** Update `apps/api/README.md` (or create
      `apps/api/scripts/README.md`) documenting `emit_openapi.py`
      and `make openapi` / `make openapi-check`.
- [ ] **T5.5** Create `packages/client-sdk/README.md` covering public
      API + regen flow.
- [ ] **T5.6** Update root `README.md` layout diagram and any phase
      status mentions.
- [ ] **T5.7** Update `specs/EXECUTION_PLAN.md`:
      - Phase 2 row marked complete.
      - Phase 2e row points to `specs/phase-2e-openapi-sdk-deploy/`.
- [ ] **T5.8** Run the **full** local pipeline:
      - `make openapi-check` — green.
      - `pnpm install --frozen-lockfile` — clean.
      - `pnpm --filter @contricool/client-sdk lint`
        (if Biome is configured for the package; otherwise skip) +
        `test:coverage` — green.
      - `pnpm --filter @contricool/client lint && typecheck && test:coverage`
        — green.
      - `cd apps/infra && pytest` — green.
      - `pnpm --filter @contricool/client build:web` — succeeds.
      - `node apps/client/scripts/check-bundle-size.mjs` — under hard
        limit.
- [ ] **T5.9** `gitleaks detect --staged` — clean.
- [ ] **T5.10** Open PR titled
      `feat(phase-2e): OpenAPI + client SDK + production web deploy`
      with the design + requirements summary in the body.
- [ ] **T5.11** Address pr-code-reviewer findings; re-run CI; merge
      after green.

## Verification (manual, post-deploy)

After merge to main, deploy.yml runs:
- `pnpm --filter @contricool/client-sdk build` — generates types.
- `pnpm --filter @contricool/client build:web` — emits `dist/`.
- `cdk deploy Contricool-Dev-Api Contricool-Dev-Web` — uploads new
  bundle to S3 + invalidates CloudFront.
- Smoke `curl https://<dev-cf>/v1/health` — 200.
- Smoke `curl https://<dev-cf>/` — 200, body contains `<script`.
- Manual approval gate.
- Same for prod.

After dev deploy completes:

- Open `https://<dev-cf-domain>/` in a browser — auth login form
  renders (no more "ContriCool — coming soon" placeholder).
- Sign up with a fresh email → check inbox → verify-email →
  log in → land on `/dashboard`. Same flow as Phase 2d's manual test
  but now without `pnpm dev:web` running.
- Hard reload while signed in — refresh cookie attaches → land on
  `/dashboard`.
- Local-dev sanity check: `pnpm --filter @contricool/client dev:web` against the
  dev API → CORS error from Phase 2d should now be gone.

If both prod and dev URLs serve the working auth flow end-to-end,
Phase 2e is shippable.
