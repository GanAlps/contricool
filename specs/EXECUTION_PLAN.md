# ContriCool — Execution Plan

This is the **phased build plan** that takes us from an empty repo to a soft-launchable v1. Every phase has explicit sub-tasks, required tests (positive + negative), and a **manual verification checkpoint** that must pass before the next phase begins. Every phase aligns with one or more designs in this folder; references are inline.

**Cardinal rules** (from `CLAUDE.md`):
1. No secrets / env-specific identifiers in source — every phase ends with a clean `gitleaks` scan.
2. Cost-and-abuse guardrails ship in the same CDK deploy as the feature, not after.
3. Negative tests for auth/security have the same blocking weight as positive tests.

**Estimated timeline** (solo dev, ~10 weeks total):

| Phase | Focus | Est. duration |
|---|---|---|
| 0 | Repo bootstrap + safety nets | 2–3 days |
| 1 | AWS account, OIDC, minimal stacks, "hello world" | 5–7 days |
| 2 | Authentication & Identity (Cognito + signup/login) | 2 weeks |
| 3 | Friends (add/list/remove) | 3–4 days |
| 4 | Transactions: create + read + list + balance | 2 weeks |
| 5 | Transactions: edit + delete + restore + audit | 5–7 days |
| 6 | Observability & operations hardening | 5–7 days |
| 7 | Pre-launch polish + privacy + load probe | 1–2 weeks |

Phases are sequential; a phase does not start until its predecessor's checkpoint passes.

---

## Phase 0 — Repo Bootstrap & Safety Nets ✅ COMPLETE

**Goal**: an empty repo on GitHub with every safety net (red-line enforcement) wired up before the first line of feature code is written.

**Why first**: red-line 1 says "no secrets in source." If we wait to add gitleaks until after we have code, we've already lost the race.

### Tasks

- [x] Initialize git repo locally; `gh repo create contricool --public`.
- [x] Add `.gitignore` covering: `*.env*`, `.venv/`, `node_modules/`, `dist/`, `build/`, `cdk.out/`, `cdk.context.json`, `*.pem`, `*.key`, `secrets/`, `.DS_Store`, `__pycache__/`, `.pytest_cache/`, `coverage/`.
- [x] Add `.gitleaks.toml` with project-specific deny rules:
  - AWS access key patterns (`AKIA[0-9A-Z]{16}`).
  - JWT shape detection.
  - Custom regex blocking `*.cloudfront.net`, `*.execute-api.*.amazonaws.com`, `*.cognito-idp.*.amazonaws.com`, raw 12-digit AWS account numbers.
- [x] Add `lefthook.yml` pre-commit hooks: `ruff check --fix` (Python staged), `mypy` (Python), `biome check --apply` (TS staged), `gitleaks detect --staged`, `make openapi-check` (if API touched).
- [x] Add root `package.json` + `pnpm-workspace.yaml` declaring workspaces `apps/*` and `packages/*`.
- [x] Add `Makefile` with stub targets: `dev-up`, `api-test`, `client-test`, `infra-diff`, `infra-deploy-dev`, `openapi`, `openapi-check`, `lint`, `format`.
- [x] Create skeleton folders with `.gitkeep`: `apps/api/`, `apps/client/`, `apps/infra/`, `packages/openapi/`, `packages/client-sdk/`, `specs/runbooks/`.
- [x] Add root `README.md` with: project blurb, prerequisites (Python 3.12, Node 22, pnpm 9, AWS CLI, CDK), quick-start commands, link to `CLAUDE.md`.
- [x] Push initial commit to `main`.

### GitHub repo settings (one-time, via UI or `gh` CLI)

- [x] **Branch protection on `main`**: require PR before merging; require status checks (`lint`, `test`, `cdk-diff`, `openapi-check`); require linear history; squash-merge enabled; force-push disabled; deletion disabled.
- [x] **Secret scanning + push protection** enabled (free for public repos).
- [x] **Dependabot security updates** enabled.
- [x] **Environments → `prod`** created with required reviewer = repo owner; wait timer optional.

### Phase-0 verification (manual)

- [x] Try to commit a file containing the string `AKIA1234567890ABCDEF` → blocked by lefthook + gitleaks.
- [x] Try to commit a file containing `d12345abc.cloudfront.net` → blocked by gitleaks.
- [x] Try to push directly to `main` → blocked by branch protection.
- [x] Open a no-op PR → CI fires (even if it's just a no-op pipeline at this point).

### Phase-0 deliverables

- Repo on GitHub at `https://github.com/<org>/contricool`.
- `CLAUDE.md`, `README.md`, `.gitignore`, `.gitleaks.toml`, `lefthook.yml`, `Makefile`, `pnpm-workspace.yaml`, root `package.json`.

### Phase-0 checkpoint

**Pass criteria**: a synthetic commit attempt with a fake AWS key is blocked, branch protection prevents direct push to main, GitHub secret scanning is on. CLAUDE.md and the design corpus are committed and visible.

---

## Phase 1 — AWS Account, OIDC & "Hello, World" ✅ COMPLETE 2026-04-29

**Goal**: end-to-end CI/CD pipeline working — a placeholder static page on CloudFront default domain plus a `/v1/health` Lambda, deployed via GitHub Actions OIDC, rolled out dev → manual approval → prod, with budget/alarm scaffolding live.

**Why before features**: validates the entire AWS bootstrap, OIDC federation, CDK structure, and deploy pipeline. Discover any bootstrap pain *here*, not while debugging an auth flow.

### 1a — AWS account foundation (manual, one-time) ✅ COMPLETE

- [x] Verify the AWS account email + billing.
- [x] **Hardware MFA on the root account**; remove any root-account access keys.
- [x] Set up **IAM Identity Center** (free) with the developer's user; assume a `Contricool-Admin` permission set with MFA for day-to-day work. No long-lived IAM users.
- [x] Enable **CloudTrail** in all regions, send to a dedicated audit S3 bucket with 90-day retention.
- [x] Configure **AWS Budgets** at $20 (warn) and $30 (critical) on the account total, filtered by `app=contricool` tag → SNS → developer's email.
- [x] Set the **SNS SMS account-level monthly spend limit to $5** at MVP (`set-sms-attributes` API or console). Combined with per-identity OTP rate limits, $5 covers ~125 India SMS or ~775 US SMS per month — well above MVP traffic.
- [x] Bootstrap CDK: `cdk bootstrap aws://<account>/us-west-2`. Also bootstrap us-east-1 separately once we register a custom domain — ACM certs for CloudFront must originate in us-east-1 even though all other resources live in us-west-2.

### 1b — `apps/infra` CDK skeleton ✅ COMPLETE (PR #3, merged 2026-04-28)

- [x] `apps/infra/pyproject.toml` with `aws-cdk-lib`, `constructs`, `aws-cdk.aws-lambda-python-alpha`.
- [x] `apps/infra/app.py` with two env configs (`dev`, `prod`) per Design 3.
- [x] Initial stacks (Web+Edge merged per design comment to dodge CDK's auto-bucket-policy stack-cycle):
  - `Contricool-Shared` — IAM OIDC provider + 3 deploy roles + AWS Budgets + CloudTrail trail + SNS alerts topic.
  - `Contricool-<env>-Api` — Lambda function returning `{"status": "ok"}` for `/v1/health`; reserved concurrency = 100; SnapStart enabled; stage-level throttling 5,000 RPS / 10,000 burst per CLAUDE.md red-line 2.
  - `Contricool-<env>-Web` — S3 bucket (private, BlockPublicAccess.BLOCK_ALL) + CloudFront distribution per env with path-based behaviors (`/v1/*` → APIGW, `/*` → S3 with SPA fallback CF Function); holds the placeholder `index.html`.
  - `Contricool-<env>-Monitoring` — alarm placeholders (lambda-errors, apigw-5xx) + dashboard (prod only).
  - **Deferred** to Phase 2 / 4: separate `Data` and `Auth` stacks (added when Cognito + DDB land).
- [x] CDK Aspect: every bucket has `BlockPublicAccess.BLOCK_ALL`; every Lambda has reserved concurrency set; CDK-internal provider Lambdas exempted via construct-path tokens. Aspect fails synth if violated.
- [x] CDK Aspect: every resource carries `app=contricool`, `env=<env>` tags.

### 1c — Hello-world Lambda ✅ COMPLETE (bundled into PR #3)

- [x] `apps/api/Dockerfile` with `python:3.12-slim` base + AWS Lambda Web Adapter binary copied from `public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0`.
- [x] `apps/api/app/main.py` with FastAPI + uvicorn entry, single `/v1/health` route returning `{"status":"ok","env":<env>,"version":"0.0.1"}`.
- [x] `apps/api/pyproject.toml` with FastAPI, uvicorn, aws-lambda-powertools.
- [x] `apps/api/tests/test_health.py` with positive test + env-default test + no-auth test (3 tests, 100% coverage).

### 1d — GitHub Actions skeleton

### 1d — GitHub Actions skeleton ✅ COMPLETE (PR #6 + follow-ups #8/#10/#11; pipeline green at run 25082189963)

- [x] `.github/workflows/ci.yml` (already shipped in Phase 0): jobs `gitleaks`, `lint`, `test`, `cdk-diff` (PR-only with PR-readonly OIDC role), `openapi-check` (placeholder until Phase 2).
- [x] `.github/workflows/deploy.yml` (push to main): cdk deploy `Contricool-Dev-*` via OIDC → smoke `/v1/health` → wait for `prod` environment approval → cdk deploy `Contricool-Prod-*` (CDK reuses dev's content-addressed ECR image — no second build) → smoke `/v1/health` → push `release/YYYY-MM-DD-sha7` tag.
- [x] `.github/workflows/rollback.yml` (manual `workflow_dispatch`): takes a `release/...` tag, validates format + main-ancestry, peels annotated tag to commit (`refs/tags/X^{}`) before merge-base check, runs `cdk deploy Contricool-Prod-*` from the rolled-back source. Operator runbook at `specs/runbooks/rollback.md`.
- [x] GitHub repo variables `AWS_DEPLOY_ROLE_DEV/PROD/PR_RO`, `AWS_REGION`, `CONTRICOOL_ALERTS_EMAIL` and secret `AWS_ACCOUNT_ID` populated via `specs/runbooks/first-deploy.md`.

### 1e — Static "coming soon" page ✅ COMPLETE (bundled into PR #3)

- [x] `apps/client/static/index.html` (one-shot; later overwritten when real Expo build lands) with minimal HTML: "ContriCool — coming soon" + a small footer.
- [x] CDK `Web` stack uploads this file via `s3deploy` construct.
- [x] CloudFront default-behavior CF Function rewrites unknown paths to `/index.html`.

### Phase-1 tests

- `apps/api/tests/test_health.py` — positive test on `/v1/health`.
- `apps/infra/tests/test_aspects.py` — synthesize each stack and assert the BlockPublicAccess and reserved-concurrency Aspects fire.
- CI smoke test — `curl https://d-<id>.cloudfront.net/v1/health` returns 200.

### Phase-1 verification (manual) ✅ COMPLETE 2026-04-29 at run 25082189963

- [x] Open the **dev CloudFront URL** in a browser → "ContriCool — coming soon" renders.
- [x] `curl https://<dev-cf-domain>/v1/health` → `200 {"status":"ok","env":"dev","version":"0.0.1"}`.
- [x] In GitHub Actions: deploy workflow finishes dev, waits for approval. Click "Approve" → prod deploys.
- [x] **Same checks against prod URL.** `200 {"status":"ok","env":"prod","version":"0.0.1"}`.
- [x] In CloudWatch console, confirm alarm topic exists and is subscribed to email. (`Contricool-Alerts` SNS topic, subscription confirmed.)
- [ ] **Deferred**: Force a fake billing event by setting Budgets threshold to $0.01 → email arrives within ~24h. (Not blocking; Budget is wired in CDK and will fire naturally as MTD approaches the $20/$30 thresholds.)
- [ ] **Deferred**: Manually invoke a "trigger 5xx" Lambda once to confirm the alarm-on-error path works. (Phase 6 will exercise every alarm during the observability hardening pass.)

### Phase-1 deliverables

- AWS account configured with budgets, MFA, CloudTrail, IAM Identity Center.
- All six CDK stacks deployed in dev + prod (mostly placeholders).
- Two CloudFront URLs serving the placeholder page.
- `/v1/health` Lambda live.
- GitHub Actions CI + deploy pipeline functional with OIDC.

### Phase-1 checkpoint

**Pass criteria**: dev and prod CloudFront URLs both return the placeholder; `/v1/health` returns 200 on both; deploy workflow completes both envs end-to-end with a manual approval; budgets + SMS spend cap + at least one CloudWatch alarm wired and sending email; `gitleaks` clean; no resource was created via the AWS console (everything in CDK).

---

## Phase 2 — Authentication & Identity ✅ COMPLETE 2026-04-29

**Goal** (achieved): a user can sign up with email (phone optional, unverified), verify their email, log in, refresh their session, and see their own profile (name + currency). Aligned with **Designs 4, 7, 13** and the email-only auth scope in CONSTRAINTS.md.

**Why next**: every subsequent feature requires authenticated callers.

**Sub-phase rollout** (each shipped as its own PR, gated by `deploy.yml`):

| Sub-phase | Scope | Spec | Status |
|---|---|---|---|
| 2a | CDK Auth + Data stacks + PII salt SSM | `specs/phase-2a-cognito-ddb-foundation/` | ✅ PR #13 |
| 2b | Backend `app/core/` (config, principal, observability, lookup_hash, middleware) | `specs/phase-2b-app-core/` | ✅ PR #14 |
| 2c | Backend `auth` feature (signup/verify/login/refresh/forgot/reset + rate-limit + JWT verifier) | `specs/phase-2c-auth-feature/` | ✅ PR #15 |
| 2c-fixes | Stage→Route DependsOn (#16), Lambda version on code change (#17), Phase 2c deps in Lambda image (#18), USER_PASSWORD_AUTH on app clients (#19), 401-cause logging (#21), two-token pattern (#22) | inline | ✅ PRs #16–#22 |
| 2d | Expo client foundation + auth screens | `specs/phase-2d-client-auth-foundation/` | ✅ PR #20 |
| 2e | OpenAPI + SDK regen + production web deploy | `specs/phase-2e-openapi-sdk-deploy/` | ✅ PR #23 |
| 2e-fixes | SDK bearer on /auth/logout (#24), id-token-in-Authorization two-token contract (#25), CORS allow `x-cognito-access-token` (#26) | inline | ✅ PRs #24–#26 |

### Deferred follow-ups (small standalone PRs)

- **Powertools idempotency on `POST /v1/auth/signup`** — original Phase 2c R1.5 deferral; not blocking real usage because Cognito rejects duplicates with `UsernameExistsException` → 409 `EMAIL_EXISTS`.
- **Per-screen empty-form a11y test sweep** (Phase 2d NB2) — current N25 test only covers the generic Form component.
- **Concurrent in-flight 401 dedup** (Phase 2e NB) — Phase 3 follow-up; Phase 2's auth surface only ever single-flights.
- **`x-cognito-access-token` bypassing the JWT authorizer on OPTIONS preflight** — preflight currently returns 401 with the right CORS headers, which browsers accept but is cosmetically odd. Investigate when traffic justifies it.

### 2a — Cognito infrastructure (CDK Auth stack)

- [ ] `Contricool-<env>-Auth` stack: User Pool (`contricool-<env>`) with:
  - Required attributes: `email`, `name`.
  - Optional unverified attribute: `phone_number` (E.164 if provided; never used for search/auth at MVP).
  - Custom attribute: `custom:user_id` (string, max 26 — for ULID).
  - Password policy: 10+ chars, complexity per Design 4.
  - Email sender: Cognito-managed (`no-reply@verificationemail.com`).
  - **No SMS configuration** — phone verification dropped at MVP (CONSTRAINTS.md / Design 4).
  - SignUp confirmation requires email only.
- [ ] App clients (no secret): `web`, `ios`, `android`. Allowed flows: `USER_SRP_AUTH` + `REFRESH_TOKEN_AUTH`. Refresh validity 30d, access 1h.
- [ ] CDK output: User Pool ID, App Client IDs (consumed by API Lambda env vars + frontend build).

### 2b — Users DDB table (CDK Data stack)

- [ ] `ContriCool-Users-<env>` table: PK + SK string, **one GSI** (GSI1 polymorphic for email-hash lookup + friend-max view). No phone-related GSI at MVP — see Design 7 / CONSTRAINTS.md "Path to re-introduce phone verification."
- [ ] On-demand billing.
- [ ] PITR enabled in prod.
- [ ] DDB Streams enabled in prod (no consumer yet).
- [ ] KMS CMK in prod (alias `alias/contricool-prod`); AWS-managed key in dev.
- [ ] TTL attribute `ttl` configured for `RATE#` and (future) `IDEMPOTENCY#` rows.

### 2c — PII salt (CDK Shared stack addition)

- [ ] `/contricool/<env>/pii-salt` SSM SecureString parameter, 32-byte random hex, encrypted with the project CMK in prod.
- [ ] Lambda execution role has `ssm:GetParameter` + `kms:Decrypt` for this parameter only.

### 2d — Backend `auth` feature (`apps/api/app/features/auth/`)

- [ ] `cognito_client.py` — boto3 wrapper with retries and error mapping (`UsernameExistsException` → 409 `EMAIL_EXISTS`, `NotAuthorizedException` → 401 `INVALID_CREDENTIALS`, etc.).
- [ ] `rate_limit.py` — DDB-backed rate-limiter using `RATE#<hash>` rows; three caps per identity (OTP per hour, OTP per day, by channel); conditional update for race safety.
- [ ] `service.py` — signup, verify-email (writes META row on email confirmation), login, refresh, logout, forgot-password, reset-password.
- [ ] `routes.py` — FastAPI router mapping endpoints from Design 8.
- [ ] `models.py` — Pydantic v2 request/response schemas.
- [ ] `README.md` describing the feature, env vars, public endpoints.

### 2e — `app/core/` shared backend infrastructure

- [ ] `config.py` — load env vars (table names, pool ID, etc.) from SSM Parameter Store at cold start; fail fast if missing.
- [ ] `principal.py` — `Principal` dataclass; built from JWT claims by middleware.
- [ ] `policy.py` — pure-function authz helpers (will gain rules in Phases 3–5).
- [ ] `observability.py` — Powertools Logger with denylist (`email`, `phone`, `password`, `code`, `otp`, `Authorization`, `Cookie`, `set-cookie`, `secret`, `token`, `refresh_token`, `id_token`, `access_token`), Metrics, Tracer.
- [ ] `lookup_hash.py` — HMAC-SHA-256 with the SSM-fetched salt; module-scope salt cached after first read.
- [ ] FastAPI middleware: request_id injection, JWT-claims extraction into `request.state.principal`, structured request logging.

### 2f — Frontend client foundation (`apps/client/`)

- [ ] Bootstrap Expo SDK 52 project: `pnpm create expo-app apps/client --template blank-typescript`.
- [ ] Add Expo Router 4, NativeWind 4, `aws-amplify`, `expo-secure-store`, TanStack Query, Zustand, React Hook Form, Zod, lucide-react-native.
- [ ] Copy initial react-native-reusables primitives needed for auth screens: `Button`, `Input`, `Card`, `Toast`, `Form`.
- [ ] `app/_layout.tsx` configures Amplify, sets up QueryClientProvider, Toaster, theme.
- [ ] Routes under `(auth)`: `login`, `signup`, `verify`, `forgot-password`, `reset-password`.
- [ ] `(app)/_layout.tsx` placeholder authenticated layout that just shows "Welcome, <name>" + Logout.
- [ ] `(app)/dashboard.tsx` placeholder for now (full content in Phase 4).
- [ ] `lib/auth.ts` — Amplify config + custom storage adapter for refresh tokens (web throws on refresh-token writes, native uses `expo-secure-store`).
- [ ] `lib/api.ts` — `openapi-fetch` client with auth interceptor (401 → refresh-once-and-retry).
- [ ] Auth state via Zustand store wrapping Amplify Hub events.

### 2g — `packages/client-sdk` (initial generation)

- [ ] First `make openapi` run: dump FastAPI OpenAPI spec to `packages/openapi/openapi.yaml`; generate `packages/client-sdk/src/schema.d.ts`.
- [ ] Commit both artifacts; CI gates on drift.

### Phase-2 tests

**Backend (positive)**:

- Signup happy path → 202 PENDING_VERIFICATION; Cognito user exists; **no DDB row yet**.
- Verify email → 200; account CONFIRMED; **still no DDB row**.
- Verify phone → 200; phone verified; **DDB user row written** with `display_name`, `currency`, `status=active`, GSI1 EMAIL hash, GSI2 PHONE hash.
- Login → 200; tokens returned; refresh cookie set on web simulation.
- Refresh → 200; new tokens.
- Forgot-password + reset-password happy path.

**Backend (negative — required by red line 3)**:

- Signup with invalid email → 422 with field-level error.
- Signup with non-E.164 phone → 422.
- Signup with weak password → 422 (Cognito rejects).
- Signup with duplicate email → 409 EMAIL_EXISTS.
- Verify email with bad code → 401 / 429.
- Login before verification complete → 403 ACCOUNT_NOT_ACTIVE (we enforce in addition to Cognito).
- Login with bad password → 401 INVALID_CREDENTIALS.
- Login after 5 wrong passwords → Cognito-throttled.
- Refresh with no cookie → 401.
- Refresh with tampered cookie → 401.
- 6th OTP request in 1 hour → 429 RATE_LIMITED.
- 11th OTP request in 1 day → 429.
- API call to `/v1/me` with no Authorization → 401.
- API call with expired JWT → 401.
- API call with tampered JWT → 401.
- API call with JWT issued by a different Cognito pool → 401.
- Logging assertion: structured log lines never contain raw email or phone (test the redactor).
- PII test: `AdminGetUser` is not called from any code path that returns to a non-self user.

**Frontend**:

- Component tests for login/signup/verify forms (validation, submit, error display).
- Auth-state hook tests.

### Phase-2 verification (manual)

- [ ] Sign up with your real email + phone on dev. Receive both codes (Cognito-managed sender for email, SNS SMS for phone). Both verifications complete.
- [ ] Land on placeholder dashboard showing "Welcome, <your name>".
- [ ] Log out, log back in. Refresh the page → still logged in (cookie + access-token refresh works on web).
- [ ] Spam the "resend code" button → 4th attempt blocked with friendly 429 message.
- [ ] Sign up with the same email again → 409 with friendly message.
- [ ] Open DDB console → see your user row with hashed email + phone GSI projections; **no raw email/phone in any attribute**.
- [ ] Open CloudWatch Logs → confirm no log line contains raw email/phone/password.
- [ ] **Negative tests in CI all green.**

### Phase-2 deliverables

- Cognito User Pool live; DDB Users table live with KMS encryption; PII salt in SSM.
- All `/v1/auth/*` endpoints functional.
- Auth screens functional on the Expo web build.
- CI passes positive + negative test suite at 99% coverage on `auth` feature.

### Phase-2 checkpoint

**Pass criteria**: signup-to-login round-trip works for a real email + phone; rate-limit triggers correctly; DDB carries no raw PII; logs carry no raw PII; all negative tests green; CloudFront URL still serves the static page for non-auth routes (because we haven't built dashboard content yet).

---

## Phase 3 — Friends

**Goal**: User A adds User B by exact **email**; both immediately see the friendship; either can remove. Aligned with **Designs 5, 6, 7** (simplified friendship model) and CONSTRAINTS.md "Friend search/add is by email only at MVP."

**Sub-phase rollout**:

| Sub-phase | Scope | Spec |
|---|---|---|
| 3a | Backend `friends` feature (repo, service, routes, rate-limit, error mapping, tests) | TBD — `specs/phase-3a-friends-backend/` |
| 3b | Frontend friends UI (list, detail, add-friend modal) consuming the regenerated SDK | TBD — `specs/phase-3b-friends-client/` |

### Tasks

- [ ] **3a — Backend `friends` feature** (`apps/api/app/features/friends/`):
  - `repository.py` — canonical-pair friendship rows; **email-hash GSI1 lookup only** (phone is unverified-metadata-only at MVP per CONSTRAINTS.md).
  - `service.py` — add (with USER_NOT_FOUND, CONFLICT, success), list, remove. Per-user rate-limit on add (30/hour).
  - `routes.py` — `POST /v1/friends/add`, `GET /v1/friends`, `DELETE /v1/friends/{user_id}`, `GET /v1/friends/{user_id}/balance` (returns 0 net for now — no transactions yet).
  - `policy.py` updates in `app/core/`: `is_friend(a, b)` helper.
  - `make openapi` regenerates `packages/openapi/openapi.yaml` and SDK schema; CI drift gate.
- [ ] **3b — Frontend friends UI** (`apps/client/app/(app)/friends/`):
  - `index.tsx` — friend list page with empty state.
  - `[userId].tsx` — friend detail; balance shows 0.
  - "Add friend" sheet/modal triggered from friend list — email input, error handling for 404/409/422 (`INVALID_IDENTIFIER` if anything but email)/429.

### Phase-3 tests

**Positive**:

- Add friend by email → bilateral friendship row; both users in each other's `GET /v1/friends`.
- List friends → returns expected display name + since-date.
- Remove friend → row gone; friend not in lists.

**Negative (required)**:

- Add with non-email identifier (e.g. phone) → 400 `INVALID_IDENTIFIER` (CLAUDE.md red-line 3 entry: "Friend-add via phone identifier — reject 400 INVALID_IDENTIFIER (email-only at MVP)").
- Add with no matching email → 404 USER_NOT_FOUND.
- Add yourself → 422 SELF_ADD_FORBIDDEN.
- Add an existing friend → 409 CONFLICT.
- Add via missing/invalid Authorization → 401.
- Remove a non-existent friendship → 404.
- 31st add request in an hour → 429.
- `GET /v1/friends/{user_id}` does not return friend's email or phone in any field.
- User C (not friends with A or B) cannot enumerate users by trying random emails — caps the request to USER_NOT_FOUND/CONFLICT only, no extra info leaked.

**Frontend**:

- Component tests for add-friend modal validation + error states.

### Phase-3 verification (manual)

- [ ] Sign up two test accounts: User A (`a@example.com`) and User B (`b@example.com`).
- [ ] As A, open `/friends`, click "Add friend", enter `b@example.com` → see B in friend list.
- [ ] As B (separate browser/profile), refresh `/friends` → see A in list (auto-bilateral).
- [ ] As A, try to add `bogus@example.com` → friendly 404 message.
- [ ] As A, try to add `b@example.com` again → friendly 409.
- [ ] As A, remove B → both lists empty.

### Phase-3 deliverables

- Friend feature live end-to-end on dev.
- 99% test coverage on `friends` feature with negative test suite.

### Phase-3 checkpoint

**Pass criteria**: bilateral friend add works; remove works; rate-limit fires; PII never leaks via friend endpoints.

---

## Phase 4 — Transactions: Create + Read + List + Balance

**Goal**: Three users (all mutual friends) can create transactions among themselves, list their own transactions, list transactions with a specific friend, and see correct balances. Aligned with **Designs 5, 6, 7**.

**Why this is two weeks**: split-method math, member/payer validation, cross-table TransactWriteItems, balance computation, and the highest-stakes UX (the add-transaction form) all live here.

### 4a — Transactions DDB table (CDK Data stack)

- [ ] `ContriCool-Transactions-<env>`: PK + SK string, one GSI (GSI1 user→txns).
- [ ] On-demand billing; PITR + Streams in prod; KMS CMK in prod.

### 4b — Backend `transactions` feature (`apps/api/app/features/transactions/`)

- [ ] `splits.py` — `equal`, `amount`, `share`, `percent` algorithms; `Decimal` arithmetic; rounding-remainder absorption rules; **Hypothesis property tests** asserting `sum(owed_amount) == amount` for all valid inputs.
- [ ] `balance.py` — pure-function pair balance computation.
- [ ] `models.py` — Pydantic v2: `Transaction`, `TransactionMember`, `Payer`, request/response schemas.
- [ ] `repository.py` — `TransactWriteItems` spanning Users (friendship ConditionChecks) + Transactions (META + MEMBER rows + AUDIT).
- [ ] `service.py` — create (with friendship verification), get, list mine, list with friend (two GSI1 queries + intersection), balance.
- [ ] `routes.py` — `POST /v1/transactions`, `GET /v1/transactions`, `GET /v1/transactions/{id}`, `GET /v1/transactions?friend_id=X`, `GET /v1/friends/{id}/balance` (now actually computes).
- [ ] Idempotency via `aws-lambda-powertools.idempotency` decorator on `POST /v1/transactions`, backed by `IDEMPOTENCY#<user>#<key>` rows in Transactions table with 24h TTL.

### 4c — Frontend transaction UI

- [ ] `(app)/dashboard.tsx` — recent activity (last 10), summary cards "Total you owe" / "Total owed to you".
- [ ] `(app)/transactions/index.tsx` — paginated list with filter chips.
- [ ] `(app)/transactions/new.tsx` — the add-transaction form per Design 10's state diagram. Sections: name, amount, date, members (friend picker, max 10), paid-by (subset of members), split method (segmented control with per-method input rows), note.
- [ ] `(app)/transactions/[txnId]/index.tsx` — read-only detail view (edit/delete in Phase 5).
- [ ] Friend detail page (`/friends/[userId]`): now lists transactions with that friend, shows computed net balance.
- [ ] Hooks: `useTransactions`, `useTransaction`, `useCreateTransaction`, `useFriendBalance`.
- [ ] React Hook Form + Zod schemas mirroring server Pydantic models.

### Phase-4 tests

**Positive**:

- Create equal-split transaction; per-member `owed_amount` correct.
- Create amount-split; sum equals amount.
- Create share-split with mixed shares; rounding remainder absorbed.
- Create percent-split summing to 100; correct distribution.
- Create transaction with multiple payers; balances split proportionally.
- Get transaction; list mine; list with friend (paginated).
- Balance with friend X correctly computed across many transactions.
- Idempotent retry returns cached response.
- Hypothesis: every valid `(amount, members, split_method, args)` produces `sum(owed_amount) == amount`.

**Negative (required)**:

- Create with non-friend member → 422 NOT_FRIEND.
- Create not including self in members → 422 SELF_NOT_MEMBER.
- Create with single member → 422 MIN_MEMBERS.
- Create with 11 members → 422 MAX_MEMBERS.
- Create with mismatched currency (member's currency != txn currency) → 422 CURRENCY_MISMATCH.
- Create with `split_method=percent` and percents summing to 99 → 422 PERCENT_SUM.
- Create with `split_method=amount` and owed sum != amount → 422 OWED_SUM.
- Create with payer not in members → 422 PAYER_NOT_MEMBER.
- Create with paid sum != amount → 422 PAID_SUM.
- Create with negative amount → 422 INVALID_AMOUNT.
- Create with date 1 year in the future → 422 INVALID_DATE.
- Get transaction as non-member → 404 (mask).
- List my transactions never returns transactions where I'm not a member.
- List with friend X never returns transactions where X is not a member.
- Idempotency-key collision across users → 409 (different user, same key).
- POST without idempotency-key → 400 IDEMPOTENCY_KEY_REQUIRED.
- Concurrent friendship-removal between create-validate and create-write → friendship ConditionCheck fails → 422 NOT_FRIEND.
- All auth negative cases (no JWT, expired, tampered, wrong-pool).

**Frontend**:

- Add-transaction form happy path + per-section validation.
- Currency formatting tests.
- Friend-picker excludes non-friends.

### Phase-4 verification (manual)

- [ ] Sign up three test accounts A, B, C; cross-add as friends.
- [ ] As A, open `/transactions/new`, create "Dinner at Joe's" $30, equal split among A/B/C, A paid all → 201.
- [ ] As A, open `/dashboard` → see "B owes you $10", "C owes you $10".
- [ ] As B, open `/dashboard` → see "You owe A $10".
- [ ] As B, open `/friends/<A's user_id>` → see the dinner transaction; balance shows -$10 (B owes A).
- [ ] As C, settle up with A: create a `settlement` transaction, $10, A and C members, C paid → C and A balance now 0; B unchanged.
- [ ] Try with currency-mismatched friends (sign up D in INR; add D as friend of A) → A cannot include D in a USD transaction; UI blocks; if forced, server 422.

### Phase-4 deliverables

- Transactions table live; transactions feature complete on backend; UI happy-path on frontend.
- Hypothesis tests pass on splits.
- 99% test coverage on `transactions` feature.

### Phase-4 checkpoint

**Pass criteria**: end-to-end transaction creation with three real users; balances correctly computed; all negative tests green; idempotency works on retry.

---

## Phase 5 — Transactions: Edit, Delete, Restore, Audit

**Goal**: Creator can edit any of their transactions (with optimistic concurrency), soft-delete, and restore within 30 days. Aligned with **Designs 5, 6, 7, 13**.

### Tasks

- [ ] **Backend**:
  - `PUT /v1/transactions/{id}` with `If-Match: <updated_at>` → DDB ConditionExpression on `creator_id` + `updated_at`. Re-validates members, payers, splits.
  - `DELETE /v1/transactions/{id}` (soft delete) — sets `deleted_at`; creator-only.
  - `POST /v1/transactions/{id}:restore` — sets `deleted_at = null` if `now - deleted_at < 30d`; creator-only.
  - AUDIT row written on every mutation with prior snapshot of META + MEMBER rows.
  - Cleanup Lambda: daily EventBridge schedule → hard-delete soft-deleted rows older than 30d, audit rows older than 90d post-hard-delete. Separate IAM role.
- [ ] **Frontend**:
  - Transaction detail page: show edit/delete buttons only when `creator_id == me`.
  - `(app)/transactions/[txnId]/edit.tsx` — pre-filled form with `If-Match` header from server's ETag.
  - Soft-delete UI with toast "Deleted. Undo (30s)".
  - Optimistic delete with rollback on 4xx.

### Phase-5 tests

**Positive**:

- Edit name/amount/members/splits as creator → 200; updated_at advances; AUDIT row created.
- Delete as creator → 200; absent from default lists; balance excludes it.
- Restore within 30d → 200; back in lists; balance includes it again.
- Cleanup Lambda hard-deletes a 31d-old soft-deleted transaction.

**Negative (required)**:

- Edit as non-creator member → 403 FORBIDDEN.
- Edit as non-member → 404 (mask).
- Edit with stale `If-Match` → 412 PRECONDITION_FAILED.
- Edit removing the creator from members → 422 SELF_NOT_MEMBER.
- Edit with new non-friend member → 422 NOT_FRIEND.
- Delete as non-creator → 403.
- Delete as non-member → 404.
- Restore after 30d → 410 GONE / 422.
- Restore by non-creator → 403.
- Audit rows exist for every mutation; no audit row missing.
- Soft-deleted transactions never appear in default `/v1/transactions` queries.
- Soft-deleted transactions don't affect balance computation.

**Frontend**:

- Edit/delete buttons hidden when not creator.
- Stale-edit returns 412 → user sees "Refresh and try again" message.

### Phase-5 verification (manual)

- [ ] As A, edit the dinner transaction to $36 → balances update (B owes $12, C owes $12).
- [ ] As B, try to edit → button hidden; if forced via API, 403.
- [ ] As A, delete → vanishes from lists; balances zeroed.
- [ ] As A, restore within 30s via the toast → reappears.
- [ ] Two browsers as A: edit in one, edit in the other with stale ETag → second edit gets 412.
- [ ] Manually invoke the cleanup Lambda with a fake 31d-old soft-deleted row → it's hard-deleted.

### Phase-5 deliverables

- Full transaction lifecycle (CRUD + restore + audit) live.
- Cleanup Lambda deployed in dev + prod.
- 99% test coverage on transactions feature.

### Phase-5 checkpoint

**Pass criteria**: full lifecycle works end-to-end; concurrency conflicts surface as 412; audit rows verifiable in DDB; cleanup runs nightly without error.

---

## Phase 6 — Observability & Operations Hardening

**Goal**: production-grade monitoring before any soft launch. Aligned with **Design 11**.

### Tasks

- [ ] **All CloudWatch alarms** wired in CDK (one alarm per row in Design 11's table); SNS routing P1 → email + SMS, P2/P3 → email only.
- [ ] **Composite "site is down" alarm** combining API 5xx + Lambda errors + DDB throttles for 5 min.
- [ ] **Prod CloudWatch Dashboard** with the 6 rows from Design 11.
- [ ] **Saved Logs Insights queries** stored in CDK (5xx in last hour, slow requests p95, AuthZ denials by user, idempotency replays, top 4xx codes, cold-start frequency).
- [ ] **X-Ray sampling** finalized: 10% prod, 100% dev. Service map includes all key edges.
- [ ] **`/v1/telemetry/error` endpoint** for frontend to report uncaught errors → CloudWatch Logs `/contricool-frontend-errors-<env>`. Rate-limited at API Gateway (10/min/IP).
- [ ] **Frontend error boundary + unhandled-rejection handler** posting to the telemetry endpoint.
- [ ] **`web-vitals` lib** added to the client; LCP/FID/CLS posted to telemetry endpoint as `level=metric`.
- [ ] **Runbooks** in `specs/runbooks/`:
  - `runbook-5xx.md` — what to do when API 5xx alarm fires.
  - `runbook-ddb-throttle.md`.
  - `runbook-sms-spend.md`.
  - `runbook-rollback.md` — how to invoke `rollback.yml`.
  - `runbook-pitr-restore.md`.

### Phase-6 tests

- Alarm-firing test: a Lambda that forces a 5xx error rate spike → P1 alarm fires → email + SMS arrive within 10 minutes.
- Logs Insights queries return rows during a synthetic load.
- X-Ray traces show full chain: client → CloudFront → APIGW → Lambda → DDB Users + DDB Transactions + Cognito.
- Frontend error boundary triggered manually → log entry appears in `/contricool-frontend-errors-prod`.

### Phase-6 verification (manual)

- [ ] Force a 5xx burst (e.g., temporarily set env var to break a route, deploy, hit the route 20x, redeploy clean) → SMS arrives on phone; email arrives.
- [ ] Open prod dashboard; all panels render with data.
- [ ] Trigger a frontend uncaught error in dev (throw in a button handler) → telemetry log appears.
- [ ] Walk through `runbook-5xx.md` end-to-end; confirm steps are accurate.

### Phase-6 deliverables

- All alarms in CDK; prod dashboard live; runbooks committed.

### Phase-6 checkpoint

**Pass criteria**: every alarm has been *manually triggered at least once* and the corresponding notification arrived; runbooks are accurate; X-Ray service map matches the design.

---

## Phase 7 — Pre-Launch Polish, Privacy & Load Probe

**Goal**: ship-ready. Aligned with **Designs 12, 13**.

### 7a — Privacy & data lifecycle

- [ ] Account deletion flow: `DELETE /v1/me` → set `status=deactivated`, `AdminDisableUser` + `AdminUserGlobalSignOut`.
- [ ] Cleanup Lambda extension: hard-delete deactivated accounts after 30d (Users hard-delete + Transactions members anonymized + payers anonymized in META + Cognito `AdminDeleteUser`).
- [ ] `GET /v1/me/export` — user-initiated JSON export of own data; rate-limited 1/day.
- [ ] **Privacy Policy** drafted at `/privacy` page on the web client, content reviewed against CCPA + India DPDP requirements.
- [ ] **Terms of Service** drafted at `/terms` page.
- [ ] **Grievance officer** contact in Privacy Policy (the dev's email).

### 7b — Security review

- [ ] **IAM Access Analyzer** run; resolve any high-severity findings.
- [ ] **CDK aspect audit** — every bucket BlockPublicAccess.BLOCK_ALL; every Lambda has reserved concurrency; no `*` actions on execution roles; every resource carries `app=contricool` + `env=*` tags.
- [ ] **CORS lockdown** verified: only known origins allowed.
- [ ] **Response headers** verified live: HSTS, CSP, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- [ ] **CloudTrail** verified delivering to audit bucket.
- [ ] **Negative test sweep**: re-run the full negative-test suite from `CLAUDE.md` against prod-like env.

### 7c — SES domain decision (DLT/SMS deferred entirely)

- [ ] Phone verification is dropped at MVP (Design 4 / CONSTRAINTS.md); no DLT registration, no toll-free / 10DLC originator work for v1.
- [ ] Decide whether to register `contricool.com` pre-launch:
  - If yes: ACM cert in **us-east-1** (mandatory for CloudFront — even though our primary region is us-west-2) covering `contricool.com` + `*.contricool.com`; Route 53 hosted zone; SES domain verification + DKIM/SPF/DMARC in us-west-2; switch Cognito to SES; activate friend-invite emails.
  - If no: launch on default CloudFront URL; defer SES + invite emails post-launch.

### 7d — WAF activation decision

- [ ] Decide on WAF: rate-based rule only ($5/mo) at launch is recommended in CLAUDE.md. Flip the CDK feature flag and redeploy.

### 7e — Load probe

- [ ] **Synthetic load test** against dev env: 50 concurrent simulated users for 10 minutes — sign up, add transactions, list, settle. Tools: `artillery` or `k6`.
- [ ] Validate p95 < 600ms, no 5xx, no DDB throttle, no Lambda throttle.
- [ ] Validate cost: total AWS bill from the load probe < $1.

### 7f — Documentation polish

- [ ] Root `README.md` updated with: how to run, how to deploy, link to `CLAUDE.md`, link to Privacy Policy.
- [ ] Each `apps/<x>/` and `apps/api/app/features/<x>/` has a current `README.md`.
- [ ] **Launch runbook** in `specs/runbooks/launch.md` — go/no-go checklist for the first user-facing release.

### Phase-7 tests

- All Phase 0–6 test suites still green.
- Account-deletion test: full flow + verify 30d-later cleanup.
- Privacy export test: structure of returned JSON matches expectations.

### Phase-7 verification (manual)

- [ ] Account-deletion flow: register → delete → cleanup → all rows gone, all anonymizations correct.
- [ ] Export own data: receive JSON containing every transaction + friendship.
- [ ] Privacy Policy + Terms accessible at `/privacy` + `/terms`.
- [ ] Load probe results filed in `specs/runbooks/launch.md`.
- [ ] Run through the launch runbook checklist; every item green.

### Phase-7 deliverables

- Account deletion + export endpoints live.
- Privacy Policy + Terms.
- Optional: domain registered + SES configured + invite emails active.
- Load probe results.
- Launch runbook.

### Phase-7 checkpoint

**Pass criteria**: 48-hour silent bake on prod with no P1 alarm; account deletion + export tested end-to-end; load probe meets latency + cost targets; legal pages live; launch runbook complete and walked.

---

## After Phase 7

- **Soft launch**: invite 5–10 friends to use the app for 2 weeks; collect feedback.
- **Iteration**: small changes via simple-change-mode (per global guidelines) — feedback fixes, UX polish, push notifications design (post-mobile), in-app friend-added notification, member cap raise if requested, etc.
- **Mobile launch**: when web feels stable, run `eas build --platform ios|android`, walk through App Store / Play Store submission.

---

## How phases connect to designs

| Phase | Primary designs touched |
|---|---|
| 0 | `CLAUDE.md`, all designs read once |
| 1 | 1, 3, 9, 11, 12 |
| 2 | 4, 7, 8 (auth endpoints), 13 (PII handling), 14 (Cognito-managed sender) |
| 3 | 5, 6, 7, 8 (friends endpoints) |
| 4 | 5, 6, 7, 8 (transactions endpoints), 10 (add-txn UX) |
| 5 | 5, 6, 7, 13 (audit + soft-delete) |
| 6 | 11 |
| 7 | 12, 13, 14 |

---

## What we explicitly do NOT do in v1

These are out of scope for the soft launch; they go through requirements + design when prioritized:

- Push notifications (mobile-only feature; mobile itself is post-launch).
- In-app friend-added notification feed.
- Friend-invite emails for non-platform users (deferred until SES domain is wired).
- Pending-accept friendship workflow.
- Block / unblock.
- Email or phone change flows.
- Recurring expenses.
- Receipt attachments.
- Currency conversion / multi-currency per user.
- Group concept (we do per-transaction membership, not persistent groups).
- Admin tooling / support console.
- BIMI, advanced email reputation features.
- GuardDuty, AWS Config, Synthetics canaries (deferred until traffic justifies).

---

## Plan-level open questions

1. **Domain registration timing** — defer to Phase 7 (recommended) or register at Phase 0 to have it ready throughout? Recommendation: **defer**. The team has more important things to validate first; default `cloudfront.net` works perfectly for dev and the closed-beta soft launch.
2. **DLT registration for India SMS** — **out of scope for v1** since phone verification was dropped from MVP (Design 4 / CONSTRAINTS.md). Reintroduce alongside business-registration when phone verification returns post-MVP.
3. **WAF at launch** — recommend yes, rate-based rule only ($5/mo). Confirm at Phase 7.
4. **AWS Identity Center setup** — recommend Phase 1a; confirm.
