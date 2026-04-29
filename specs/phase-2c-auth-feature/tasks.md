# Phase 2c — Auth Feature Backend — Tasks

Six implementation phases. Each phase ends with the test suite green and
coverage ≥ 99% on everything written so far. Phases ship as a single PR
(matching the Phase 2a/2b cadence) with one commit per phase.

---

## Phase 1 — Dependencies + JWT verifier + `current_principal()` dependency

- [ ] **T1.1** Add `pyjwt[crypto]>=2.9.0`, `cryptography>=43.0.0`,
      `boto3-stubs[cognito-idp,dynamodb]>=1.35.0`,
      `moto[cognitoidp,dynamodb]>=5.0.0` to `apps/api/pyproject.toml`.
- [ ] **T1.2** Implement `apps/api/app/core/security.py`:
      - `class InvalidTokenError(Exception)`.
      - `class JwtVerifier` with `verify(token) -> dict[str, object]`.
      - `PyJWKClient` cache; `kid`-miss refetch-once; explicit `iss`,
        `aud`/`client_id` per token_use, `token_use ∈ {id, access}`.
- [ ] **T1.3** Implement `apps/api/app/core/dependencies.py`:
      - `get_jwt_verifier()` — module-scope singleton, built from `config`.
      - `current_principal(request) -> Principal` (FastAPI dependency).
      - `class UnauthenticatedError(Exception)`.
- [ ] **T1.4** Tests `apps/api/tests/core/test_security.py`:
      - Positive: validly signed access token returns claims dict.
      - Positive: validly signed ID token returns claims dict.
      - Negative: tampered signature → `InvalidTokenError`.
      - Negative: expired token → `InvalidTokenError`.
      - Negative: wrong issuer → `InvalidTokenError`.
      - Negative: `token_use=other` → `InvalidTokenError`.
      - Negative: ID token with `aud` not in audience list → fail.
      - Negative: access token with `client_id` not in audience list → fail.
      - JWKs cache: same `kid` → no refetch; new `kid` → one refetch.
- [ ] **T1.5** Tests `apps/api/tests/core/test_dependencies.py`:
      - `current_principal` happy path → returns `Principal`.
      - Missing `Authorization` header → `UnauthenticatedError`.
      - Wrong scheme (`Basic …`) → `UnauthenticatedError`.
      - Token verifies but `Principal.from_claims` raises (missing
        `custom:user_id`) → `UnauthenticatedError`.
- [ ] **T1.6** Run `pytest --cov=app tests/ --cov-fail-under=99` — green.

## Phase 2 — Cognito client wrapper + error envelope

- [ ] **T2.1** Implement `apps/api/app/features/auth/errors.py`:
      `AuthError`, exception handler functions returning JSON envelope
      with `request_id` from `request.state`.
- [ ] **T2.2** Implement `apps/api/app/features/auth/cognito_client.py`:
      - `class CognitoClient` with the nine method signatures from design.md.
      - Module-scope boto3 client.
      - `_map_error(boto3.ClientError, *, path)` returns `AuthError`.
- [ ] **T2.3** Tests `apps/api/tests/features/auth/test_cognito_client.py`
      against `moto[cognitoidp]`:
      - Happy paths for all 9 methods.
      - Each error → correct `AuthError(code, http_status)`.
      - Path-dependent `NotAuthorizedException` (login vs refresh vs logout).
- [ ] **T2.4** Tests `apps/api/tests/features/auth/test_errors.py`:
      - Envelope shape, `request_id` populated, `Retry-After` set when present,
      - Pydantic ValidationError → 422 with `details: [{field, issue}, …]`.
- [ ] **T2.5** Coverage green.

## Phase 3 — Rate-limiter

- [ ] **T3.1** Implement `apps/api/app/features/auth/rate_limit.py`:
      - `class RateLimitExceeded(Exception)` with `retry_after_seconds`.
      - `consume_otp_email(email)` — Get-then-conditional-Update pattern,
        one retry on race-loss, raises `RateLimitExceeded` at cap.
- [ ] **T3.2** Tests `apps/api/tests/features/auth/test_rate_limit.py`
      against `moto[dynamodb]`:
      - First-ever request creates the row.
      - 5 calls in same hour all succeed; 6th → `RateLimitExceeded`,
        `retry_after_seconds <= 3600`.
      - Day cap: 20 succeed; 21st → `RateLimitExceeded`,
        `retry_after_seconds <= 86400`.
      - Rolled hour window (timestamp manipulation) resets hour counter.
      - Rolled day window resets both counters.
      - Concurrent race-loser retry path (mock conditional-check failure
        once, then succeeds).
      - Same email through `forgot-password` increments the same row.
- [ ] **T3.3** Coverage green.

## Phase 4 — Auth feature: signup / verify-email / resend-email-code

- [ ] **T4.1** Implement `apps/api/app/features/auth/models.py` (all 8
      request + 4 response models, `extra="forbid"`).
- [ ] **T4.2** Implement `apps/api/app/features/auth/service.py` —
      `signup`, `verify_email`, `resend_email_code` business logic.
      Wires `cognito_client`, `rate_limit`, DDB `PutItem`/`GetItem`.
- [ ] **T4.3** Implement `apps/api/app/features/auth/routes.py` — three
      route handlers; mount under `/auth`.
- [ ] **T4.4** Wire idempotency on `signup` via Powertools
      `IdempotencyConfig`; payload validation enforces 422 on
      same-key-different-body.
- [ ] **T4.5** Update `apps/api/app/main.py`:
      - Include the auth router at `/v1`.
      - Register the `AuthError` exception handler.
      - Register the Pydantic `RequestValidationError` handler.
- [ ] **T4.6** Tests `apps/api/tests/features/auth/test_signup.py`:
      - **Positive**: 202 + `user_id` + `status: PENDING_VERIFICATION`,
        Cognito `SignUp` called with normalised email + custom:user_id.
      - **N1, N2, N3, N4, N5** from requirements.md.
      - **N27**: idempotency replay does not call `SignUp` twice.
      - **N28**: idempotency mismatch → 422.
- [ ] **T4.7** Tests `apps/api/tests/features/auth/test_verify_email.py`:
      - **Positive**: 200 + DDB row written with correct GSI1PK email-hash.
      - **N6, N7, N8, N9** from requirements.md.
      - DDB `PutItem` failure post-`ConfirmSignUp` → 500 + alert log.
- [ ] **T4.8** Tests `apps/api/tests/features/auth/test_resend.py`:
      - **Positive**: 202; rate-limit row incremented.
      - **N23, N24, N26** from requirements.md.
      - Unknown email → 202 (no leak).
      - Already-confirmed → 409 `ALREADY_CONFIRMED`.
- [ ] **T4.9** Tests `apps/api/tests/features/auth/test_signup_security.py`:
      - **N29, N30** logging redaction across signup/verify/resend
        endpoints.
- [ ] **T4.10** Coverage green.

## Phase 5 — Auth feature: login / refresh / logout

- [ ] **T5.1** Implement service + route handlers for the three.
- [ ] **T5.2** Cookie helpers (set / clear) with the design's exact
      attributes (HttpOnly, Secure, SameSite=Strict, Path=/v1/auth,
      Max-Age=2592000).
- [ ] **T5.3** Tests `apps/api/tests/features/auth/test_login.py`:
      - **Positive**: 200; DDB `GetItem` populates user object; cookie
        attributes verified via `Set-Cookie` parse.
      - **N10, N11, N12, N13** from requirements.md.
- [ ] **T5.4** Tests `apps/api/tests/features/auth/test_refresh.py`:
      - **Positive**: 200; new access + id; refresh cookie unchanged.
      - **N14, N15** from requirements.md.
- [ ] **T5.5** Tests `apps/api/tests/features/auth/test_logout.py`:
      - **Positive**: 204 + cookie cleared + Cognito `GlobalSignOut` called.
      - **N16, N17, N18, N19** from requirements.md.
- [ ] **T5.6** Tests `apps/api/tests/features/auth/test_login_security.py`:
      - **N29, N30** redaction across login/refresh/logout — assert no
        password, refresh, or access token in any log line.
- [ ] **T5.7** Coverage green.

## Phase 6 — Auth feature: forgot-password / reset-password

- [ ] **T6.1** Implement service + routes.
- [ ] **T6.2** Forgot-password shares `consume_otp_email` with
      resend-email-code (same `OTP#EMAIL` row).
- [ ] **T6.3** Tests `apps/api/tests/features/auth/test_forgot.py`:
      - **Positive**: 202 even for unknown email.
      - **N20, N25** from requirements.md.
- [ ] **T6.4** Tests `apps/api/tests/features/auth/test_reset.py`:
      - **Positive**: 200.
      - **N21, N22** from requirements.md.
- [ ] **T6.5** Coverage green.

## Phase 7 — CDK wiring + synth tests

- [ ] **T7.1** Update `apps/infra/stacks/api_stack.py`:
      - Add `user_pool`, `web_client`, `ios_client`, `android_client`,
        `users_table` constructor params.
      - Build `HttpJwtAuthorizer` (alpha) or `CfnAuthorizer` fallback.
      - Add 7 explicit auth-bootstrap public routes.
      - Modify catch-all `/{proxy+}` to attach the JWT authorizer.
      - Add `RouteSettings` for login/resend/forgot throttles to the
        existing `default_stage` CFN override.
      - Add IAM grants: 8 enumerated `cognito-idp:*` actions on pool ARN;
        `dynamodb:Get/Put/Update` on Users table ARN.
- [ ] **T7.2** Update `apps/infra/app.py` to pass new params and add
      `api.add_dependency(auth)` and `api.add_dependency(data)`.
- [ ] **T7.3** Update `apps/infra/tests/test_synth.py` — assertions
      from design.md (T7-* synth tests + N31, N32, N33).
- [ ] **T7.4** Run `cd apps/infra && cdk synth Contricool-Dev-Api > /dev/null` —
      synth succeeds.
- [ ] **T7.5** Coverage green.

## Phase 8 — Documentation + final checks

- [ ] **T8.1** Write `apps/api/app/features/auth/README.md` covering the
      8 endpoints, env vars used, public API contract.
- [ ] **T8.2** Update root `README.md` with mention of auth endpoints
      now being live.
- [ ] **T8.3** Run final `pytest --cov=app tests/ --cov-fail-under=99`,
      `ruff check`, `mypy --strict apps/api apps/infra`.
- [ ] **T8.4** Open PR; address pr-code-reviewer findings; merge after
      green.

## Verification (manual, post-deploy)

After dev deploy of the merged PR:

- `curl -X POST $DEV_API/v1/auth/signup -d '{...}'` → 202.
- Check inbox for Cognito-managed-sender email with code.
- `curl -X POST $DEV_API/v1/auth/verify-email -d '{...}'` → 200.
- `aws dynamodb get-item --table-name ContriCool-Users-dev …` → META row exists.
- `curl -X POST $DEV_API/v1/auth/login -d '{...}'` → 200 + Set-Cookie.
- 6 rapid `resend-email-code` → last one 429 with `Retry-After` header.
