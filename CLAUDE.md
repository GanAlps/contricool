# ContriCool — Project Guidelines

This is the **single source of truth for how ContriCool is built and operated.** Every contributor (human or agent) reads this before writing any code. The spec design docs in `specs/` define *what* we build; this document defines *how we build it safely*.

---

## SECTION 1 — RED LINES (non-negotiable)

These three rules cannot be bent. A PR violating any of them must be rejected, period.

### RED LINE 1 — Never commit secrets, credentials, or environment-specific identifiers

The repository is **public**. Treat every commit as a press release.

**Never commit, in any file, in any branch, ever:**

- AWS access keys, secret keys, session tokens.
- Cognito User Pool IDs, App Client IDs, Identity Pool IDs.
- DynamoDB table ARNs.
- KMS key ARNs or aliases.
- CloudFront distribution IDs or domain names (e.g. `d1abc123.cloudfront.net`).
- API Gateway IDs.
- SES/SNS topic ARNs or DKIM keys.
- AWS account IDs.
- Database connection strings.
- Third-party API keys.
- Any URL containing `<account-id>.dkr.ecr.*.amazonaws.com`, `<api-id>.execute-api.*.amazonaws.com`, `cognito-idp.*.amazonaws.com/<pool-id>`.
- OIDC provider thumbprints or role ARNs containing the account ID.

**Even non-secret, env-specific identifiers stay out of code.** Knowing our dev CloudFront domain leaks attack surface; knowing our prod Cognito pool ID makes targeted phishing easier. *Anything that varies between dev and prod is environment data, and environment data is not source code.*

**Where they live instead:**

| What | Where |
|---|---|
| Secrets that need rotation (none at MVP, but e.g. third-party API keys later) | AWS Secrets Manager |
| Non-secret env config (table names, pool IDs, region, build commit) | SSM Parameter Store (Standard tier, free); read at Lambda cold start |
| GitHub Actions variables (deploy role ARNs, ECR repo URI) | GitHub Repo Variables — values managed by repo admin via the GitHub UI |
| Local-dev values | `apps/api/.env.local` and `apps/client/.env.local`, both in `.gitignore` |
| Frontend build-time public values (Cognito pool ID, region) | Inlined at build time from CI environment variables; **never committed to source** |

**Defenses, in layers:**

1. `.gitignore` covers `.env*`, `*.pem`, `*.key`, `cdk.context.json`, anything in `secrets/`, `dist/`, `build/`.
2. `gitleaks` runs as a pre-commit hook (via `lefthook`) — blocks the commit on detection of high-entropy strings, AWS key patterns, JWT shapes, etc.
3. `gitleaks` runs again in CI — blocks the merge.
4. GitHub repo-level **secret scanning + push protection** enabled (free for public repos).
5. **Hand-rolled grep guard in CI**: blocks any string matching `cloudfront\.net`, `*.execute-api.<region>.amazonaws.com`, `cognito-idp.<region>.amazonaws.com/<pool-id>`, raw 12-digit AWS account IDs in ARN context, etc. (See `.gitleaks.toml` for the exact rules — region-agnostic.)
6. Code review (self-review for solo): if you see a hardcoded URL, table name, or ID in a PR, kick it back.

**If a secret is ever committed**, even momentarily: **rotate it immediately**, force-push is not enough, the value is permanently in git history. Then file an issue documenting the incident.

### RED LINE 2 — Cost-and-abuse guardrails are wired from day one

Our budget is $30/month. A single SMS-pumping attack or a Lambda-runaway-loop can blow that in hours. Every guardrail listed in the designs is **mandatory in code from the first deploy**, not a "we'll add it later."

The following are not aspirational; they ship with the first CDK deploy:

| Guardrail | Where enforced |
|---|---|
| AWS Budget alert at $20 (warn) and $30 (critical) | CDK `Contricool-Shared` stack, tag-filtered per-env |
| SNS SMS account-level monthly spend cap of **$5** | CDK custom resource setting `MonthlySpendLimit` on `set-sms-attributes` (raise via Service Quotas request once volume justifies it) |
| Lambda **reserved concurrency = 100** on `contricool-api-<env>` | CDK Lambda function config |
| API Gateway **per-route throttling** for `/v1/auth/*`, `/v1/friends/request`, `/v1/auth/login` | CDK API Gateway HTTP API route settings |
| API Gateway **stage-level throttling** at 5,000 RPS / 10,000 burst | CDK stage default |
| Per-identity OTP rate limits (3/h, 10/day SMS; 5/h, 20/day email) | App-layer `rate_limit.py` writing to `ContriCool-Users` `RATE#<hash>` rows; **enforced before** calling Cognito |
| Per-user friend-request rate limit (30/h) | App-layer rate-limit table |
| Per-IP rate limit on `/v1/telemetry/error` (10/min/IP) | API Gateway throttling on the route |
| WAF rate-based rule (2000 req/5min/IP → block 10min) | CDK feature-flagged; **enabled at first sign of abuse**, not deferred indefinitely |
| CloudWatch alarm: SES bounce > 5% | CDK monitoring stack |
| CloudWatch alarm: SES complaint > 0.1% | CDK monitoring stack |
| CloudWatch alarm: SNS MTD spend > $4 (80% of cap) | CDK monitoring stack |
| CloudWatch alarm: Lambda errors > 1% | CDK monitoring stack |
| CloudWatch alarm: DDB throttles > 0 | CDK monitoring stack (per table) |
| `S3 BlockPublicAccess.BLOCK_ALL` on every bucket | CDK Aspect — enforced across all buckets |
| KMS CMK encrypts both DDB tables in prod | CDK Aspect — enforced |
| TLS 1.2 minimum, HTTP redirects to HTTPS | CDK CloudFront default |
| CORS strict allowlist | CDK API Gateway HTTP API config |
| Strict-Transport-Security, CSP, X-Content-Type-Options, Referrer-Policy | CDK CloudFront response-headers policy |
| IAM least-privilege: no `*` actions on Lambda execution roles | CDK construct review + IAM Access Analyzer (run quarterly) |

**The principle**: anything that costs money on the wrong path has a cap, an alarm, or both. **Caps are configured in CDK so they redeploy with the stack** — they are not human-managed via the AWS console.

### RED LINE 3 — Auth and security enforcement is covered by negative tests

Every authentication, authorization, and rate-limit rule has at least one **negative test** that proves it rejects the disallowed path. **Negative tests for auth and security have the same blocking weight as positive tests** — a PR that only adds positive tests for an auth-touching change is rejected.

**Required negative test classes:**

| Class | Example |
|---|---|
| **Missing JWT** | request to `/v1/me` with no `Authorization` header → 401 |
| **Expired JWT** | forge a JWT with `exp` in the past → 401 |
| **Wrong-pool JWT** | a JWT from a different Cognito pool → 401 |
| **Tampered JWT** | flip a bit in the signature → 401 |
| **Wrong-user authorization** | user A tries to GET user B's transaction → 404 (mask) |
| **Non-creator edit** | user B (member) tries to PUT user A's transaction → 403 |
| **Non-friend transaction creation** | user A creates txn including non-friend C → 422 |
| **Stale-edit conflict** | edit with stale `If-Match` → 412 |
| **Rate-limit hit** | 6th OTP request in an hour → 429 |
| **Idempotency replay** | second POST with same key returns the cached response (not a new resource) |
| **Currency mismatch** | create txn with currency != user's currency → 422 |
| **Self-add friend** | add yourself as friend → 422 |
| **Already-friends add** | add an existing friend → 409 |
| **Non-existent friend add** | add an email/phone with no matching user → 404 USER_NOT_FOUND |
| **Cross-tenant data isolation** | user A's session never sees user B's data via any endpoint |
| **PII not in response** | `GET /v1/friends/{id}` does not return friend's email or phone |
| **Soft-deleted invisible** | `GET /v1/transactions/{id}` after delete → 404 |
| **CORS rejection** | request from an off-origin (browser-only) is denied |
| **Body-size limit** | request body > 100 KB → 413 |
| **Unsupported content-type** | `application/x-www-form-urlencoded` body → 415 |

**Test layout:** mirror `apps/api/app/features/<name>/` with `apps/api/tests/<name>/`. Each test file groups positive and negative cases; the file name's `_security.py` suffix flags pure-security tests for the audit.

**Coverage floor: 99% per the global development guideline.** No exceptions.

**Auth/AuthZ test infrastructure**: a `conftest.py` fixture set provides:

- `valid_jwt(user_id, groups=[])` — mints a Cognito-shaped JWT signed with a test key.
- `expired_jwt`, `tampered_jwt`, `wrong_pool_jwt` — pre-built bad tokens.
- `seeded_user(currency='USD')`, `seeded_friendship(a, b)`, `seeded_transaction(creator, members)` — DDB fixtures via moto.
- `as_user(user_id)` — context manager that wraps `httpx.AsyncClient` with the right Authorization header.

These fixtures are part of the test foundation, not per-test boilerplate.

---

## SECTION 2 — Project Architecture (one-page summary)

Detailed designs live in `specs/`. The architecture in one paragraph:

ContriCool is a Splitwise-lite app. **One Expo codebase** under `apps/client` ships to web today (S3 + CloudFront) and iOS/Android tomorrow (EAS Build). **One Lambda** under `apps/api` runs FastAPI on Python 3.12 arm64 via the AWS Lambda Web Adapter, with SnapStart enabled. **Two DynamoDB tables** — `ContriCool-Users-<env>` (3 GSIs covering email + phone lookup + friendship reverse) and `ContriCool-Transactions-<env>` (1 GSI covering user→txns). **Cognito User Pool** owns identity (email + phone, both verified). **One CloudFront distribution per env** routes `/v1/*` to API Gateway HTTP API, everything else to S3, all on the AWS-default `cloudfront.net` domain at MVP. Single AWS account, two CDK stack groups (`Contricool-Dev-*`, `Contricool-Prod-*`) isolated by resource-name prefix, IAM scope, and tags.

**Read these designs in order if you're new:**

1. `specs/CONSTRAINTS.md` — the cross-cutting answers (scale, geography, currency, budget, timeline, team).
2. `specs/01-high-level-architecture/design.md` — the system shape.
3. `specs/02-tech-stack/design.md` — language/framework picks.
4. `specs/03-hosting-infrastructure/design.md` — AWS topology.
5. The rest are reference; consult per topic.

---

## SECTION 3 — Repo Structure

```
contricool/
  apps/
    api/                  # FastAPI Lambda (Python)
      app/
        features/{auth,profile,friends,transactions,notifications}/
        core/             # config, ddb client, cognito client, policy, principal
        main.py           # FastAPI app + uvicorn entry (LWA forwards to it)
      tests/<feature>/
      pyproject.toml
      Dockerfile
    client/               # Expo + RN + RN-Web (single codebase for web + native)
      app/                # Expo Router file-based routes
      components/ui/      # react-native-reusables primitives, copy-pasted
      features/
      lib/
      package.json
      app.json
      tailwind.config.ts
    infra/                # AWS CDK (Python)
      stacks/{shared,data,auth,api,web,edge,monitoring}_stack.py
      app.py
  packages/
    openapi/openapi.yaml      # generated artifact, committed
    client-sdk/               # generated TS SDK (openapi-typescript + openapi-fetch)
  specs/                  # design docs (this folder)
  .github/workflows/      # CI + deploy
  pnpm-workspace.yaml
  package.json
  CLAUDE.md               # this file
  README.md
  .gitignore
  .gitleaks.toml          # gitleaks config
  lefthook.yml            # pre-commit hooks
  Makefile                # cross-language commands
```

---

## SECTION 4 — Coding Conventions

### Python (apps/api, apps/infra)

- **Python 3.12.** No older.
- Shared venv: `/home/oshogupta/workspace/master-venv`. **Never create a project-local venv.**
- Lint/format: **ruff** (replaces black + flake8 + isort).
- Types: **mypy --strict**. No `Any`, no untyped function returns.
- Models: **Pydantic v2** for all request/response/DDB shapes.
- Decimals: `decimal.Decimal` for all monetary values. Never floats.
- Logging: `aws-lambda-powertools.Logger` with the project denylist enabled. Never log raw `email`, `phone`, `password`, `code`, `otp`, `Authorization`, `Cookie`, `set-cookie`, `secret`, `token`, `refresh_token`.
- AWS calls via `boto3`; client objects created once at module scope, reused across invocations.
- Tests: `pytest` + `moto` (AWS mocks). Coverage floor 99%.

### TypeScript (apps/client, packages/client-sdk)

- **TypeScript 5.6+, strict mode**. No `any`.
- Lint/format: **biome** (replaces ESLint + Prettier).
- Components: function components + hooks. No class components.
- Styling: **NativeWind** classNames only. No inline styles, no `StyleSheet.create` (NativeWind handles both).
- Forms: **React Hook Form + Zod**.
- Server state: **TanStack Query**. UI state: `useState` or **Zustand** when crossing routes.
- API calls: **only through `@contricool/client-sdk`** (the generated typed client). Never raw `fetch` to our own API.
- Tests: **vitest** + `@testing-library/react-native`.

### Both languages

- File names: snake_case (Python) / kebab-case (TS).
- Public functions/classes: documented purpose where non-obvious; no docstrings on private helpers.
- No comments explaining *what*; comments only for *why* — and only when the why is non-obvious.
- Every feature folder has a `README.md` describing what it does, public API, env vars used.

---

## SECTION 5 — Workflow & Git Hygiene

- **Branch off `main`**: `feature/<short-name>` or `fix/<short-name>`.
- **No direct push to `main`** (branch protection enforces).
- **Squash-merge only** (linear history).
- **Conventional Commits** for the squash message: `feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`.
- **No `--no-verify`, no `--no-gpg-sign`**, no skipping pre-commit hooks.
- **No force-push to shared branches** (`main` can't be force-pushed; feature branches OK).
- Pre-commit hooks (lefthook): ruff/mypy on Python staged files, biome/tsc on TS staged files, gitleaks on all staged files, `make openapi` if API changed.
- After every API change: `make openapi` regenerates `packages/openapi/openapi.yaml` and `packages/client-sdk/src/schema.d.ts`. CI gates this — drift fails the build.

---

## SECTION 6 — Operational Rules

### Production is reachable only from CI

- **Nobody runs `cdk deploy` from a laptop against prod.** Ever.
- Production secrets/config never touch a developer machine.
- Day-to-day prod observability via CloudWatch (read-only) is fine; mutations require a PR.
- AWS console access for prod is **read-only by default**; mutating actions go through CDK + GitHub Actions.

### Console clicks are documented

- If you ever click a button in the AWS console for prod (rare emergency), file a runbook entry in `specs/runbooks/<date>-<topic>.md` describing what was clicked, why, and what the CDK code change is to reconcile.
- CloudFormation drift detection runs weekly in CI; alarms on drift.

### IAM Identity Center, not IAM users

- No long-lived IAM users with console passwords for daily use.
- AWS access via IAM Identity Center (free) with MFA required.
- Root account: hardware MFA, no programmatic keys, used only for billing setup.

### Dependencies

- Lockfiles (`pnpm-lock.yaml`, `pyproject.toml`/`uv.lock`) **committed**.
- **Dependabot enabled** for security updates.
- New dependencies require justification in the relevant design doc — no slipping in libraries via PR without a paper trail.

### Documentation

- Every feature has a `README.md` (per global guideline).
- The root `README.md` is updated whenever the way to run the app changes, a new env var appears, or a major feature lands.
- Design changes happen in `specs/`, not in code comments.

---

## SECTION 7 — Testing Requirements

| Layer | Tool | Coverage floor |
|---|---|---|
| API unit + integration | pytest + moto | 99% |
| Frontend unit + component | vitest + RN Testing Library | 99% on logic, 80%+ on UI |
| End-to-end (web) | Playwright against dev env, nightly | smoke-only |
| End-to-end (native) | Maestro on EAS-built artifacts (post-MVP) | smoke-only |

- **Tests live in the same phase as the code they test** (per global guideline).
- **Negative tests for auth/security** required for every PR touching auth, authorization, rate limiting, validation, or PII handling.
- **Property-based tests with Hypothesis** for `splits.py` (split math correctness across all inputs).
- LocalStack + moto for AWS service mocks in CI; no calls to real AWS from tests.

---

## SECTION 8 — Cost Discipline (review monthly)

- AWS Budgets dashboard: review the first of every month.
- If MTD spend > $20 (account total) or SNS SMS MTD > $4 (80% of the $5 SMS cap), investigate **before** month-end. Common culprits:
  - SNS SMS spend (check `SMSMonthToDateSpentUSD`).
  - CloudWatch Logs ingest (check log-group ingestion rates).
  - DDB on-demand requests (check ConsumedRCUs/WCUs).
- If a runaway is detected: **disable the offending feature flag in CDK and redeploy**; do not let the bill keep rising while debugging.
- Quarterly: review IAM Access Analyzer findings; tighten any over-permissive policies.

---

## SECTION 9 — When in Doubt

- **Question before building.** If a requirement is unclear, ask — don't assume.
- **No gold-plating.** Only build what's in the spec. Improvements go through the requirements stage.
- **One thing at a time.** Finish what's in progress before starting something new.
- **Small tasks.** If a task takes more than a focused sitting, break it down further.
- **No dead code.** Remove code that's no longer used rather than commenting it out.

---

## Appendix — Why these rules exist

- **RED LINE 1** (no secrets/env data in source): The repo is public. Two contributors over four years on Splitwise's competitor leaked dev API URLs that turned into real attack vectors. We don't get to relearn that.
- **RED LINE 2** (cost guardrails from day one): "We'll add the rate limit later" is how people wake up to a $4,000 SMS bill from one weekend of SMS pumping. The design has the limits; this rule enforces that they're in code, not on a TODO list.
- **RED LINE 3** (negative tests): Auth bugs that pass positive tests are common. A test that asserts "Bob *can* read his own transaction" doesn't prove Bob *can't* read Alice's. Both must exist.
