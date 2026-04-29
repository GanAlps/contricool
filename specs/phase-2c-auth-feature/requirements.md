# Phase 2c — Auth Feature Backend — Requirements

## Overview

Phase 2c implements the **email-only authentication backend** that turns the
infrastructure shipped in Phase 2a (Cognito User Pool + ContriCool-Users DDB
table) and the shared core shipped in Phase 2b (`config`, `principal`,
`observability`, `lookup_hash`, `middleware`) into a working set of public
HTTP endpoints. After 2c, a real user can:

1. Sign up with email + password (`POST /v1/auth/signup`).
2. Confirm their email with the Cognito-emailed code (`POST /v1/auth/verify-email`).
3. Log in via SRP and receive a JWT access token + an HttpOnly refresh-token
   cookie (`POST /v1/auth/login`).
4. Refresh tokens via the cookie (`POST /v1/auth/refresh`).
5. Log out, revoking all refresh tokens (`POST /v1/auth/logout`).
6. Recover access via forgot/reset password (`POST /v1/auth/forgot-password`,
   `POST /v1/auth/reset-password`).
7. Resend the email verification code, rate-limited (`POST /v1/auth/resend-email-code`).

Phase 2c also wires:

- **API Gateway HTTP API JWT authorizer** in front of the Lambda for
  `/v1/*` routes that require auth, while explicitly leaving the auth
  bootstrap routes public.
- **Lambda-side JWT verifier** (`current_principal()` FastAPI dependency)
  for defense-in-depth and clean `Principal` construction inside handlers.
- **OTP rate-limiter** writing to `ContriCool-Users-<env>` `AUTH_RATE#…`
  rows: 5 email-OTP requests/hour, 20/day per email identity.
- **Idempotency** on `POST /v1/auth/signup` via Powertools idempotency
  decorator backed by the Users table.

Phase 2c is **backend only**. The Expo client and SDK regen ship in
Phase 2d/2e.

## Scope

### In scope (this phase)

- `apps/api/app/features/auth/` — full auth feature module: `routes.py`,
  `service.py`, `models.py`, `cognito_client.py`, `rate_limit.py`,
  `errors.py`, `README.md`.
- `apps/api/app/core/security.py` — JWT signature/claims verifier using
  Cognito JWKs (auto-fetched + cached at module scope).
- `apps/api/app/core/dependencies.py` — `current_principal()` FastAPI
  dependency producing an `app.core.principal.Principal`.
- Updates to `apps/api/app/main.py` — mount the auth router, install a
  global error envelope handler, register the auth-rate-limiter table
  client.
- New deps in `apps/api/pyproject.toml` — `pyjwt[crypto]`, `cryptography`,
  `boto3-stubs[cognito-idp,dynamodb]`, `moto[cognitoidp,dynamodb]`.
- `apps/infra/stacks/api_stack.py` — pass-through wiring for the Cognito
  pool (issuer URL + audience list) into an API Gateway HTTP API JWT
  authorizer; explicit auth-public routes for the eight bootstrap
  endpoints; IAM grants for `cognito-idp:*` (scoped to the pool ARN) and
  `dynamodb:GetItem/PutItem/UpdateItem` on the Users table ARN.
- `apps/infra/app.py` — pass `user_pool`, the three client IDs, and the
  Users-table ARN/name into `ApiStack`.
- `apps/infra/tests/test_synth.py` — synth assertions for the JWT
  authorizer, the public-route exemption list, the per-route throttling on
  `/v1/auth/login` and `/v1/auth/resend-email-code`, the Lambda IAM scope
  (`cognito-idp:*` only on the pool ARN; DDB only on Users table ARN).
- Backend tests — positive and negative (red-line 3) for every endpoint;
  coverage floor 99%.

### Out of scope (later phases)

- `/v1/me` profile endpoints (Phase 3 — profile feature).
- Friends / transactions endpoints (Phases 4, 5).
- Expo client + auth screens (Phase 2d).
- OpenAPI export + SDK regen (Phase 2e).
- WAF rate-based rule deployment (Phase 6 — gated on first signs of abuse
  per CLAUDE.md red-line 2).
- SES custom-domain email sender (Phase 7+, post `contricool.com`
  registration).
- Phone verification, SMS, federation (Google/Apple), MFA — all deferred
  per CONSTRAINTS.md and Design 4.

## Functional Requirements

### R1 — Signup (`POST /v1/auth/signup`)

- **R1.1** — Accepts `{email, password, name, currency, phone?}` JSON body.
  All fields except `phone` are required.
- **R1.2** — Validates `email` format, `password` against Cognito policy
  (≥10 chars, upper+lower+digit+symbol — server doesn't recheck Cognito's
  rules; just relies on Cognito's rejection), `name` 1-128 chars,
  `currency` ∈ `{USD, INR}` (matching Design 7), `phone` must match E.164
  if provided.
- **R1.3** — Generates a server-side ULID for `custom:user_id` and calls
  Cognito `SignUp(username=email, password, attrs={email, name,
  custom:user_id, phone_number?})`. The phone is stored as Cognito's
  optional unverified `phone_number` attribute only; never used elsewhere.
- **R1.4** — On success returns **202 Accepted** with body
  `{user_id, status: "PENDING_VERIFICATION"}`. The `user_id` is the
  generated ULID, **not** Cognito's `sub`.
- **R1.5** — Idempotency: when an `Idempotency-Key` header is supplied
  (UUIDv4), the response is cached for 24h keyed by `(client_ip + email +
  key)` so a network retry does not create duplicate Cognito users.
- **R1.6** — Error mapping:
  - Cognito `UsernameExistsException` → **409** `EMAIL_EXISTS`.
  - Cognito `InvalidPasswordException` → **422** `INVALID_PASSWORD` with
    field-level `details: [{field: "password", issue: <Cognito msg>}]`.
  - Pydantic validation failure → **422** `VALIDATION_ERROR`.
  - SNS-related errors (we don't send SMS — never expected) → **500**
    `INTERNAL`.

### R2 — Verify email (`POST /v1/auth/verify-email`)

- **R2.1** — Accepts `{email, code}` JSON body.
- **R2.2** — Calls Cognito `ConfirmSignUp(username=email, code)`.
- **R2.3** — On success **and only on success**, writes the META row to
  `ContriCool-Users-<env>`: PK=`USER#<user_id>`, SK=`META`, attributes
  `display_name, currency, status="active", created_at, GSI1PK=EMAIL#<hash>,
  GSI1SK=USER#<user_id>` per Design 7. The `user_id` is read from
  Cognito's `custom:user_id` attribute via `AdminGetUser` (server-only,
  never exposed). The email-hash is the HMAC-SHA-256 from
  `app.core.lookup_hash`.
- **R2.4** — DDB write uses `ConditionExpression="attribute_not_exists(PK)"`
  so a duplicate `verify-email` call (e.g. user clicks twice) is a
  no-op (200 OK; idempotent path).
- **R2.5** — Returns **200** `{email_verified: true, account_active: true}`.
- **R2.6** — Error mapping:
  - Cognito `CodeMismatchException` → **401** `INVALID_CODE`.
  - Cognito `ExpiredCodeException` → **401** `INVALID_CODE`.
  - Cognito `NotAuthorizedException` ("user is already confirmed") →
    **200** with the same body (idempotent retry).
  - Cognito `UserNotFoundException` → **404** `USER_NOT_FOUND` (we don't
    leak existence beyond what an email validation already implies — same
    rationale as Design 5/6).
  - DDB write failure after Cognito `ConfirmSignUp` succeeds → **500**
    `INTERNAL` and a CloudWatch error-level log line `verify_email_ddb_write_failed`
    (alarm hooks added in Phase 6).

### R3 — Resend email code (`POST /v1/auth/resend-email-code`)

- **R3.1** — Accepts `{email}` JSON body.
- **R3.2** — Per-identity rate limit: **5 requests/hour, 20/day** per
  `email`. Limit row PK = `AUTH_RATE#<email-hash>`, SK = `OTP#EMAIL`,
  attributes `attempts_hour, hour_window_started_at, attempts_day,
  day_window_started_at, ttl=now+24h`. Conditional `UpdateItem`
  increments counters and roll the window when expired.
- **R3.3** — Rate-limit hit → **429** `RATE_LIMITED` with `Retry-After`
  header (seconds until window roll).
- **R3.4** — Below limit → call Cognito `ResendConfirmationCode(username=email)`.
- **R3.5** — Returns **202** `{status: "RESENT"}`.
- **R3.6** — A non-existent email yields **202** with the same body — we
  do **not** leak existence here (different from R2 where the user has
  already proven knowledge of the email by signing up).
- **R3.7** — `InvalidParameterException` from Cognito (email already
  confirmed) → **409** `ALREADY_CONFIRMED`.

### R4 — Login (`POST /v1/auth/login`)

- **R4.1** — Accepts `{email, password}` JSON body. **MVP server-side
  flow**: backend calls Cognito `InitiateAuth(USER_PASSWORD_AUTH,
  AuthParameters={USERNAME, PASSWORD})` against the `web` app client.
  - **Why USER_PASSWORD_AUTH and not SRP**: at MVP the web client uses
    plain JSON to the backend (Amplify v6's SRP support on web is
    JS-side; Phase 2d wires Amplify on the client and it can switch to
    SRP transparently). Until Phase 2d ships, the web client posts the
    password to our backend over TLS, the backend forwards via
    `USER_PASSWORD_AUTH`. **TLS in transit is the only password
    protection at MVP**; CLAUDE.md red-line 2 tooling (rate-limiting,
    WAF) defends the credential surface.
- **R4.2** — On success, fetches the user's META row from DDB to populate
  `user.{user_id, name, currency}` in the response body.
- **R4.3** — Sets the refresh token in an HttpOnly cookie:
  `Set-Cookie: rt=<refresh>; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth;
  Max-Age=2592000`. The `Path=/v1/auth` scopes the cookie to auth
  endpoints only — it never leaks to friends / transactions paths.
- **R4.4** — Response **200** body:
  ```json
  {
    "access_token": "<jwt>",
    "id_token": "<jwt>",
    "expires_in": 3600,
    "user": { "user_id": "01J...", "name": "Alice", "currency": "USD" }
  }
  ```
- **R4.5** — Error mapping:
  - Cognito `NotAuthorizedException` ("Incorrect username or password",
    "User is disabled") → **401** `INVALID_CREDENTIALS`.
  - Cognito `UserNotConfirmedException` → **403** `ACCOUNT_NOT_ACTIVE`.
  - Cognito `PasswordResetRequiredException` → **403** `PASSWORD_RESET_REQUIRED`.
  - Cognito `TooManyRequestsException` → **429** `RATE_LIMITED`.

### R5 — Refresh (`POST /v1/auth/refresh`)

- **R5.1** — Reads the `rt` cookie from the request. **No body.**
- **R5.2** — Calls Cognito `InitiateAuth(REFRESH_TOKEN_AUTH,
  AuthParameters={REFRESH_TOKEN: <rt>})` against the `web` app client.
- **R5.3** — Returns **200** `{access_token, id_token, expires_in: 3600}`.
  Refresh token unchanged (Cognito doesn't rotate it on refresh by
  default); cookie is **not** re-sent unless rotation is enabled later.
- **R5.4** — Error mapping:
  - Missing or empty `rt` cookie → **401** `MISSING_REFRESH_TOKEN`.
  - Cognito `NotAuthorizedException` (revoked / expired refresh) →
    **401** `REFRESH_FAILED` plus `Set-Cookie: rt=; Max-Age=0` to clear
    the dead cookie.

### R6 — Logout (`POST /v1/auth/logout`)

- **R6.1** — **Authenticated endpoint**: requires `current_principal()`
  to succeed (i.e. valid access token). This is the only auth endpoint
  behind the JWT authorizer.
- **R6.2** — Calls Cognito `GlobalSignOut(AccessToken=<access>)` — this
  invalidates **all** refresh tokens for the user across web + native.
- **R6.3** — Returns **204 No Content** with `Set-Cookie: rt=; Max-Age=0;
  Path=/v1/auth` to clear the web cookie.
- **R6.4** — Cognito `NotAuthorizedException` → **401**
  `UNAUTHENTICATED` (token was already invalid; still clear the cookie).

### R7 — Forgot password (`POST /v1/auth/forgot-password`)

- **R7.1** — Accepts `{email}` JSON body.
- **R7.2** — Subject to the same OTP rate-limit (R3.2): forgot-password
  shares the `OTP#EMAIL` counters because it triggers the same email
  send path.
- **R7.3** — Calls Cognito `ForgotPassword(username=email)`.
- **R7.4** — Returns **202** `{status: "RESET_CODE_SENT"}` regardless of
  whether the email exists (no enumeration).
- **R7.5** — Cognito `LimitExceededException` (Cognito's own throttle) →
  **429** `RATE_LIMITED`.

### R8 — Reset password (`POST /v1/auth/reset-password`)

- **R8.1** — Accepts `{email, code, new_password}` JSON body.
- **R8.2** — Calls Cognito `ConfirmForgotPassword(username, code,
  password)`.
- **R8.3** — Returns **200** `{password_reset: true}`.
- **R8.4** — Error mapping:
  - `CodeMismatchException` / `ExpiredCodeException` → **401**
    `INVALID_CODE`.
  - `InvalidPasswordException` → **422** `INVALID_PASSWORD`.
  - `UserNotFoundException` → **401** `INVALID_CODE` (mask).

## Non-functional Requirements

### NFR1 — JWT verification (defense in depth)

- **NFR1.1** — The Lambda re-verifies every JWT on authenticated routes
  (currently only `/v1/auth/logout`; future `/v1/me`, `/v1/friends/*`,
  `/v1/transactions/*`). API Gateway's HTTP API JWT authorizer is the
  edge layer; Lambda's `current_principal()` is the application layer.
- **NFR1.2** — Verifier checks: signature against the pool's JWKs (cached
  at module scope, refreshed on `kid` miss), `iss` ==
  `https://cognito-idp.<region>.amazonaws.com/<pool-id>`, `aud` ∈
  `{web, ios, android client_ids}` (for ID tokens) **or** `client_id` ==
  one of the three (for access tokens — Cognito access tokens use
  `client_id` not `aud`), `exp` not in the past, `token_use` ∈
  `{"id", "access"}`.
- **NFR1.3** — On any verification failure → **401**
  `UNAUTHENTICATED` with no detail (don't tell the attacker which check
  failed).
- **NFR1.4** — JWKs cache: fetched once at first verification, kept in
  module scope for the cold-start lifetime. On a `kid` miss, refetch
  once (covers the rare Cognito key rotation); persistent failure → 401.

### NFR2 — Rate-limiting

- **NFR2.1** — `email-OTP` channel cap: 5/hour, 20/day per email
  identity. Channels share-the-row across `resend-email-code` and
  `forgot-password` (both trigger the same email send).
- **NFR2.2** — `login` is **not** behind our app-rate-limit at MVP;
  Cognito's own throttling + API Gateway per-route throttling
  (5 RPS / 10 burst) cover it. Adding our own rate-limit on login would
  need to key on email + IP, which is a Phase 4-5 concern when we have
  more abuse data.
- **NFR2.3** — Per-route throttling on API Gateway HTTP API:
  - `POST /v1/auth/login`: burst 10, sustained 5/s.
  - `POST /v1/auth/resend-email-code`: burst 5, sustained 1/s.
  - `POST /v1/auth/forgot-password`: burst 5, sustained 1/s.

### NFR3 — Logging & observability

- **NFR3.1** — Every auth handler logs **only** `{event, user_id?,
  cognito_error_type?}`. **Never** log `email`, `password`, `code`,
  `phone`, JWT, or refresh-token. The Powertools redactor in
  `app.core.observability` enforces this; tests assert.
- **NFR3.2** — Each handler emits one structured INFO log line at
  success and one ERROR line on Cognito 5xx mapping. The middleware
  access log already emits a generic line per request — handlers add
  semantic context, not duplicates.
- **NFR3.3** — `request_id` is propagated from middleware into all
  handler logs (already wired in Phase 2b via `logger.append_keys`).

### NFR4 — IAM scope (least privilege)

- **NFR4.1** — Lambda execution role gets `cognito-idp:SignUp`,
  `ConfirmSignUp`, `ResendConfirmationCode`, `InitiateAuth`,
  `GlobalSignOut`, `ForgotPassword`, `ConfirmForgotPassword`,
  `AdminGetUser` only — and only on the per-env pool ARN. No `*` actions
  and no other pool ARNs.
- **NFR4.2** — DDB grants: `GetItem`, `PutItem`, `UpdateItem` on the
  Users table ARN. **No `Scan`, no `BatchWriteItem`, no `DeleteItem`.**
- **NFR4.3** — Synth tests in `apps/infra/tests/test_synth.py` assert
  the IAM policy actions and resources exactly.

### NFR5 — CDK changes

- **NFR5.1** — `ApiStack` accepts `user_pool: cognito.IUserPool`,
  `web_client: cognito.IUserPoolClient`, `ios_client`, `android_client`,
  `users_table: dynamodb.ITable` (or arns) as constructor args.
  `app.py` wires them after Auth + Data stacks construct.
- **NFR5.2** — API Gateway HTTP API gets a `HttpJwtAuthorizer` (or
  CFN-equivalent) configured with:
  - `jwt_configuration.issuer = "https://cognito-idp.<region>.amazonaws.com/<pool-id>"`
  - `jwt_configuration.audience = [web_client_id, ios_client_id, android_client_id]`
  - `identity_source = ["$request.header.Authorization"]`
  Default-route auth = NONE (so existing `/v1/health` keeps working);
  authenticated routes are **explicit** routes with the JWT authorizer
  attached.
- **NFR5.3** — Public auth-bootstrap routes are added as **explicit
  HTTP API routes** with `authorization_type=NONE`: `POST /v1/auth/signup`,
  `POST /v1/auth/verify-email`, `POST /v1/auth/resend-email-code`,
  `POST /v1/auth/login`, `POST /v1/auth/refresh`,
  `POST /v1/auth/forgot-password`, `POST /v1/auth/reset-password`.
  Authenticated route is `POST /v1/auth/logout` with the JWT authorizer.
  Catch-all `/{proxy+}` retains JWT authorizer for everything else.

## Negative-test Requirements (Red Line 3)

The following negative tests are **mandatory** for Phase 2c. Each is a
distinct test function in `apps/api/tests/features/auth/test_<area>.py`
(or `_security.py` for the pure-security cases).

### Auth-flow negatives

- N1 — Signup with malformed email → 422 `VALIDATION_ERROR`, field=email.
- N2 — Signup with phone in non-E.164 format → 422.
- N3 — Signup with currency outside `{USD, INR}` → 422.
- N4 — Signup with weak password → 422 `INVALID_PASSWORD` (Cognito-rejected).
- N5 — Signup with duplicate email → 409 `EMAIL_EXISTS`.
- N6 — Verify-email with wrong code → 401 `INVALID_CODE`.
- N7 — Verify-email with expired code → 401 `INVALID_CODE`.
- N8 — Verify-email for unknown email → 404 `USER_NOT_FOUND`.
- N9 — Verify-email called twice (already-confirmed) → 200 idempotent
  (does not re-write DDB; second `PutItem` blocked by
  `attribute_not_exists`).
- N10 — Login before email verified → 403 `ACCOUNT_NOT_ACTIVE`.
- N11 — Login with wrong password → 401 `INVALID_CREDENTIALS`.
- N12 — Login with unknown email → 401 `INVALID_CREDENTIALS` (mask).
- N13 — Login when DDB META row is missing despite Cognito CONFIRMED
  (rare reconciliation gap) → 500 `INTERNAL` + alert log.
- N14 — Refresh with no `rt` cookie → 401 `MISSING_REFRESH_TOKEN`.
- N15 — Refresh with tampered `rt` cookie → 401 `REFRESH_FAILED` +
  cookie cleared.
- N16 — Logout with no Authorization header → 401 `UNAUTHENTICATED`.
- N17 — Logout with expired access token → 401 `UNAUTHENTICATED`.
- N18 — Logout with tampered access token → 401 `UNAUTHENTICATED`.
- N19 — Logout with token from a **different Cognito pool** → 401.
- N20 — Forgot-password for unknown email → 202 (no leak).
- N21 — Reset-password with wrong code → 401 `INVALID_CODE`.
- N22 — Reset-password with weak new password → 422 `INVALID_PASSWORD`.

### Rate-limit negatives

- N23 — 6th `resend-email-code` in 1 hour → 429 `RATE_LIMITED` +
  `Retry-After` header.
- N24 — 21st `resend-email-code` in 1 day → 429 `RATE_LIMITED`.
- N25 — `forgot-password` shares the rate-limit row with
  `resend-email-code` (mixed sequence: 3 resend + 3 forgot in one hour →
  6th call 429s).
- N26 — Rate-limit `Retry-After` header is `<= 3600` and `> 0`.

### Idempotency negatives

- N27 — Signup with same `Idempotency-Key` returns the **cached** 202
  body, **not** a new Cognito user (assert `SignUp` boto3 client called
  exactly once).
- N28 — Signup with same key but **different body** → 422
  `IDEMPOTENCY_KEY_MISMATCH` (Powertools default behaviour).

### Logging negatives

- N29 — Across all 8 endpoints, no log line contains the request body's
  email, password, phone, code, or new_password.
- N30 — Across all 8 endpoints, no log line contains a JWT or refresh
  token.

### IAM / synth negatives

- N31 — Synth: Lambda IAM does not contain `cognito-idp:*` (must be
  enumerated actions).
- N32 — Synth: Lambda IAM does not contain `dynamodb:Scan` or
  `dynamodb:DeleteItem` or `dynamodb:BatchWriteItem`.
- N33 — Synth: API Gateway has no route with `authorization_type=NONE`
  except the explicit auth-bootstrap list above + `/v1/health` (catch-all
  has the JWT authorizer).

## Constraints

- **CLAUDE.md red-line 1** — No hardcoded ARNs, account IDs, pool IDs,
  client IDs in code. CDK passes ARNs at synth; Lambda reads pool/client
  IDs from SSM at cold start (already wired Phase 2b).
- **CLAUDE.md red-line 2** — Per-route throttling on
  `/v1/auth/login`, `/v1/auth/resend-email-code`, `/v1/auth/forgot-password`
  is mandatory and lives in `api_stack.py`. App-level OTP rate-limit
  (5/h, 20/day) is mandatory and lives in `rate_limit.py`.
- **CLAUDE.md red-line 3** — Every negative test above (N1-N33) ships
  with this PR. Coverage floor 99%.
- **Email-only at MVP** — phone is captured but never validated, never
  searched, never used for login/recovery. No `/v1/auth/verify-phone`,
  no `/v1/auth/resend-phone-code` endpoints (Design 4, CONSTRAINTS.md).
- **No SES yet** — Cognito's managed sender (`no-reply@verificationemail.com`)
  is the only email path at MVP. Phase 7+ migrates to SES once
  `contricool.com` registers.

## Summary

Phase 2c stands up the eight-endpoint auth backend, wires API Gateway HTTP
API JWT authorizer + Lambda-side `current_principal()`, and ships the
OTP rate-limiter. All endpoints, error mappings, and negative tests are
specified above. This is a single PR; the design.md decomposes it into
six implementation phases for ordered execution.
