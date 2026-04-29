# Phase 2b — `app/core/` shared backend infrastructure — Requirements

## Overview

Phase 2b lays the **shared plumbing** every feature module (auth, friends,
transactions, …) will need: cold-start configuration loading from SSM,
observability with PII-safe logging, the `Principal` dataclass that
authenticated requests carry, the email lookup-hash helper, and the FastAPI
middleware that injects request IDs and structured access logs.

Phase 2b is **infrastructure-only** for the API Lambda; no new endpoints, no
new business logic. Phase 2c wires the `auth` feature on top of these
helpers and adds the JWT validation middleware.

This phase realises EXECUTION_PLAN.md sub-section **2e** (`app/core/`) — the
prerequisite for **2d** (the `auth` feature).

## Requirements

### R1 — `app/core/config.py` — cold-start configuration loader

A FastAPI app instance can call `core.config.load()` once at module
import / cold start to populate a frozen `AppConfig` dataclass with values
read from AWS SSM Parameter Store under `/contricool/<env>/...`:

- `cognito_user_pool_id` — `/contricool/<env>/cognito/user-pool-id`
- `cognito_web_client_id` — `/contricool/<env>/cognito/client-id-web`
- `cognito_ios_client_id` — `/contricool/<env>/cognito/client-id-ios`
- `cognito_android_client_id` — `/contricool/<env>/cognito/client-id-android`
- `users_table_name` — `/contricool/<env>/ddb/users-table-name`
- `pii_salt` — `/contricool/<env>/pii-salt` (SecureString, decrypted)
- `env_name` — from `ENV_NAME` Lambda environment variable
- `app_version` — from `APP_VERSION` Lambda environment variable (or `0.0.1`)
- `aws_region` — from `AWS_REGION` Lambda environment variable

`load()` MUST:

- Issue a single `ssm:GetParameters` batch call (up to 10 names) — no per-key
  round trips.
- Fail fast (`RuntimeError`) if any required parameter is missing or empty.
  An empty value MUST not silently degrade to a default.
- Cache the loaded `AppConfig` in module scope; subsequent calls return the
  cached object. The cache survives Lambda warm starts.
- Be importable without side effects; only `load()` actually hits SSM.
- Be unit-testable: a `_set_for_tests(config)` helper resets the cache.

### R2 — `app/core/observability.py` — Powertools logger with PII denylist

A `core.observability.logger` is the project-wide structured logger
(`aws_lambda_powertools.Logger`). It MUST:

- Emit JSON log lines with these fields auto-included: `timestamp`,
  `level`, `service` ("contricool-api"), `request_id`, `cold_start`,
  `function_name`, `function_version`, `xray_trace_id` (when sampled),
  `env_name`.
- **Redact every value** for any key (case-insensitive, recursive) in the
  denylist below before serialising:
  ```
  email, phone, phone_number, password, code, otp,
  authorization, cookie, set-cookie,
  secret, token, access_token, id_token, refresh_token,
  ssn, credit_card,
  ```
- Replace redacted values with the literal string `[REDACTED]`.
- Provide a small helper `inject_lambda_context(handler)` decorator (re-exports
  Powertools' standard one).
- Provide a `core.observability.metrics` (`aws_lambda_powertools.Metrics`)
  and `core.observability.tracer` (`aws_lambda_powertools.Tracer`) for
  feature modules to publish custom metrics + X-Ray segments.

### R3 — `app/core/principal.py` — authenticated-request principal

A `Principal` Pydantic v2 model carries the fields an authenticated request
needs:

```
user_id: str           # ULID (custom:user_id from JWT)
email: EmailStr        # email claim (PII; never logged)
display_name: str      # name claim
groups: list[str]      # cognito:groups (empty list if absent)
token_use: Literal["id", "access"]  # token_use claim
```

`Principal.from_claims(claims: dict)` builds the principal:

- Required claims: `custom:user_id`, `email`, `name`, `token_use`.
- Missing or empty required claim → `ValueError` (callers translate to 401).
- `cognito:groups` is optional and defaults to `[]`.

The Principal does NOT verify JWT signatures — that responsibility lands in
Phase 2c's `auth` middleware. `Principal.from_claims` only validates the
shape of an already-parsed claims dict.

### R4 — `app/core/lookup_hash.py` — email lookup hash

A `core.lookup_hash.email_hash(email: str) -> str` function:

- Returns `HMAC-SHA-256(salt, normalised_email)` as a hex string.
- `normalised_email` = `email.strip().lower()`.
- Salt is read from `AppConfig.pii_salt` (so SSM access happens once at
  cold start, not per call).
- Empty / falsy / non-string input → `ValueError` (raises early; callers
  translate to 422 before any hashing).

The output format matches the `EMAIL#<hash>` convention in
`specs/07-database-data-model/design.md` (just the `<hash>` part; the
`EMAIL#` prefix is added by the repository layer in Phase 2c).

### R5 — `app/core/policy.py` — authz helpers (skeleton)

A minimal `core.policy` module with:

- `is_self(principal, target_user_id)` — boolean.
- Type stubs / `# noqa` placeholders for `is_friend(a, b)` and
  `can_edit_transaction(principal, txn)` — these get real bodies in
  Phases 3 and 5 when the data layer exists. Phase 2b leaves them as
  `NotImplementedError` so importers fail loudly if they try to use them
  prematurely.

### R6 — FastAPI middleware

A single `app.core.middleware` module exposes one function
`install_core_middleware(app)` that the FastAPI factory calls. The
middleware:

- **Request-ID injection**: read the `X-Request-Id` header if present
  (validated against ULID shape — 26 chars, Crockford alphabet); if missing
  or invalid, generate a new ULID. Set on `request.state.request_id` and
  echo back in the response `X-Request-Id` header.
- **Powertools log context**: write `request_id`, `path`, `method` into
  the structured log context for the duration of the request (via
  `logger.append_keys(...)`).
- **Access log**: emit one INFO log line per request after the response
  is built, with `path`, `method`, `status_code`, `duration_ms`. The
  PII denylist applies — query strings, headers, and bodies are NEVER
  logged.
- **No JWT handling at this phase.** Phase 2c adds a `current_principal()`
  FastAPI dependency that reads claims from a header (or the API Gateway
  authorizer event) and constructs a `Principal`.

### R7 — Tests

Tests live in `apps/api/tests/core/` and cover:

- **config.py**:
  - Happy path: 7 SSM parameters present → `AppConfig` populated correctly.
  - Negative: missing / empty parameter → `RuntimeError` with the
    parameter name in the message (caller can grep).
  - Caching: second `load()` call does not hit SSM.
  - `_set_for_tests` resets the cache.
- **observability.py**:
  - **Negative (red-line 3)**: every key in the denylist (case-insensitive,
    nested in dicts/lists) is redacted to `[REDACTED]`.
  - Non-redacted keys pass through unchanged.
  - JSON output is valid JSON.
- **principal.py**:
  - Happy path: full claims dict → `Principal` populated.
  - **Negative**: missing `custom:user_id` → `ValueError`.
  - **Negative**: empty `email` → `ValueError`.
  - **Negative**: invalid `token_use` → `ValueError`.
  - `cognito:groups` absent → empty list.
- **lookup_hash.py**:
  - Determinism: same input → same hash across calls.
  - Case + whitespace normalisation: `Foo@bar.com` and ` foo@bar.com `
    produce the same hash.
  - **Negative**: empty / non-string → `ValueError`.
  - Output is 64-char lowercase hex.
- **middleware**:
  - Request-ID echoed back in response header.
  - Invalid `X-Request-Id` (e.g., wrong length) → server-generated ULID.
  - `request.state.request_id` populated on the request scope.
  - Access log line emitted with `status_code` and `duration_ms`.
  - **Negative**: a request body containing `password=hunter2` produces
    no log line containing `hunter2`.

Coverage floor: **99% on `apps/api/app/core/`** per global guideline.

### R8 — Out of scope (handled in Phase 2c)

- JWT signature verification + JWKS caching.
- `current_principal()` FastAPI dependency.
- API Gateway HTTP API JWT authorizer wiring (Api stack change).
- Auth endpoints (`/v1/auth/...`) and the rate-limit table writes.

## Edge cases

- **Cold-start race on `config.load()`**: two parallel Lambda invocations
  on a freshly-warmed container could both call `load()`. The module-scope
  cache uses Python's `threading.Lock` to ensure exactly one SSM round trip
  per container.
- **SSM rate limits**: `GetParameters` is 40 TPS per region; well above any
  Lambda cold-start rate at our scale. No client-side throttling needed.
- **Salt secrecy**: `AppConfig.pii_salt` is treated as a secret. The
  Powertools logger redaction rules cover the `pii_salt` key by name; it
  must NEVER appear in any log line, exception message, or response body.
- **Test isolation**: `_set_for_tests()` overrides the module-level config
  cache. Tests for `lookup_hash` set a known salt; tests for downstream
  features set the full `AppConfig` shape.

## Summary

Phase 2b ships the shared backend foundation: cold-start SSM config,
PII-safe Powertools logging, a `Principal` model, the email lookup-hash
helper, and the request-ID / access-log middleware. Zero new endpoints;
zero changes to the deployed Lambda's behaviour beyond the access-log
output and an extra cold-start cost (~50 ms one-time SSM round trip).
