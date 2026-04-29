# `auth` Feature

Email-only authentication backend for ContriCool. Built on Cognito User
Pool (Phase 2a) + the Users DynamoDB table (Phase 2a) + the shared
`app.core` runtime (Phase 2b).

## Public Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/auth/signup` | none | Start signup. Returns `{user_id, status: "PENDING_VERIFICATION"}` (HTTP 202). |
| `POST` | `/v1/auth/verify-email` | none | Confirm the emailed code; activates the account and writes the `USER#…#META` row. |
| `POST` | `/v1/auth/resend-email-code` | none | Re-send the verification code (rate-limited, see below). |
| `POST` | `/v1/auth/login` | none | `USER_PASSWORD_AUTH` against Cognito. Returns `{access_token, id_token, expires_in, user{user_id, name, currency}}` and sets a `rt` HttpOnly cookie. |
| `POST` | `/v1/auth/refresh` | cookie | Read `rt` cookie, return new access + id tokens. |
| `POST` | `/v1/auth/logout` | **JWT** | Revoke all refresh tokens via Cognito `GlobalSignOut`; clears the `rt` cookie. |
| `POST` | `/v1/auth/forgot-password` | none | Send password-reset code (rate-limited; shares cap with `resend-email-code`). |
| `POST` | `/v1/auth/reset-password` | none | Confirm new password with the emailed code. |

## Rate Limiting

OTP-bearing emails (verification + password reset) are throttled per
email identity:

- **5 sends/hour**, **20 sends/day** per email.
- Counters live in `ContriCool-Users-<env>` at
  `PK=AUTH_RATE#<email-hash>`, `SK=OTP#EMAIL`.
- 429 responses include a `Retry-After` header.

## Cookie

The refresh-token cookie is set on `/v1/auth/login`, read by
`/v1/auth/refresh`, and cleared on `/v1/auth/logout` and on a 401
returned from `/v1/auth/refresh`. Attributes:

```
Set-Cookie: rt=<token>; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth; Max-Age=2592000
```

`Path=/v1/auth` keeps the cookie off non-auth paths.

## Configuration (read at cold start from SSM by `app.core.config`)

| Field | SSM Parameter |
|---|---|
| `cognito_user_pool_id` | `/contricool/<env>/cognito/user-pool-id` |
| `cognito_web_client_id` | `/contricool/<env>/cognito/client-id-web` |
| `cognito_ios_client_id` | `/contricool/<env>/cognito/client-id-ios` |
| `cognito_android_client_id` | `/contricool/<env>/cognito/client-id-android` |
| `users_table_name` | `/contricool/<env>/ddb/users-table-name` |
| `pii_salt` | `/contricool/<env>/pii-salt` (SecureString) |

## IAM (least-privilege)

The Lambda execution role is granted, via CDK in
`apps/infra/stacks/api_stack.py`:

- Eight enumerated `cognito-idp:*` actions on the per-env pool ARN — no
  `*` wildcards.
- `dynamodb:GetItem`, `PutItem`, `UpdateItem` on the Users table — no
  `Scan`, `BatchWriteItem`, `DeleteItem`.

CDK synth tests in `apps/infra/tests/test_synth.py` enforce both lists.

## Architecture

```
routes.py     ── HTTP adapter; cookie wiring; principal dependency
service.py    ── pure business logic; Cognito + DDB calls
cognito_client.py ── boto3 wrapper with stable error mapping
rate_limit.py ── DDB-backed dual-window counter
errors.py     ── AuthError envelope + global exception handlers
models.py     ── Pydantic v2 request/response models (extra="forbid")
```

`service.py` is HTTP-agnostic — future workers (e.g. nightly cleanup of
abandoned signups) can call into the same functions without dragging
FastAPI in.

## Limitations & Forward-Compat

- **Email-only at MVP.** Phone is captured optionally as an unverified
  Cognito attribute; never used for login, search, or recovery. See
  `specs/CONSTRAINTS.md` "Path to re-introduce phone verification" for
  the post-MVP plan.
- **Cognito-managed email sender** at MVP. SES with a custom domain
  arrives once `contricool.com` registers.
- **No MFA, no federation** at MVP. Both deferred to post-MVP per
  `specs/04-authentication/design.md`.
- **`USER_PASSWORD_AUTH`** is the login flow today; Phase 2d will
  introduce Amplify on the client and switch to SRP transparently.
