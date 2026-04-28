# ContriCool — Authentication Design

## Overview

This design fixes how users prove identity in ContriCool: signup, verify email, sign in, refresh tokens, and recover access. Design level: **HLD + LLD**. Headlines: **Cognito User Pool** with **email as the sole required + verified attribute** at MVP; phone is an optional unverified Cognito attribute (opaque metadata only); **Cognito-managed email sender** at MVP (no custom domain yet); **JWT-based sessions with 1-hour access tokens and 30-day refresh tokens**; **AWS Amplify Auth (v6) on the Expo client** doing SRP, refresh, and platform-secure storage transparently. **No SMS is sent at MVP** (carrier rules effectively require business registration to send public-route SMS via AWS; we defer that until pre-public-launch). Web stores the refresh token in an **HttpOnly cookie scoped to the CloudFront distribution domain** via a backend `/v1/auth/refresh` proxy; native uses `expo-secure-store` (Keychain/EncryptedSharedPreferences). Federation (Google/Apple) is deferred.

## Authentication Design

### Identity model

- **One Cognito User Pool per environment** (`contricool-dev`, `contricool-prod`).
- **Cognito holds identity only** — preferences/settings live in DynamoDB.
- Cognito attributes:
  - `email` — standard, **required, verified**.
  - `phone_number` — standard, **optional, NOT verified at MVP**. If provided, format-validated as E.164. Treated as opaque metadata; never used for login, recovery, friend search, or any other identity flow at MVP.
  - `name` — standard, mutable, required.
  - `custom:user_id` — application-level ULID, generated server-side at signup, written into Cognito on confirmation. App data in DynamoDB keys by this ULID, not by Cognito's `sub`. Portable across IdP migrations and easier in logs. **This is the only custom attribute.**
- **Currency** (and any future user setting like locale, theme, notification prefs) lives **only in `ContriCool-Users-<env>` on `USER#<id>#META`**, never in Cognito.
- **Username**: Cognito's auto-generated `sub` (UUID); we never expose it. Sign-in uses `email`.
- **Password policy**: min 10 chars, ≥1 number, ≥1 lowercase, ≥1 uppercase, ≥1 symbol; password history 3.
- **Account states**: `UNCONFIRMED` (just signed up) → `CONFIRMED` (email verified). Account becomes active on `CONFIRMED`.

### Why email-only at MVP

US carrier rules (CTIA Messaging Principles + per-carrier campaign verification, tightened across 2024) effectively require business identity (EIN, registered entity) for any public-route SMS originator — toll-free, 10DLC, short code alike. As a pre-business solo developer launch, this path is closed. The realistic options were (per the operational discussion):

| Option | Decision |
|---|---|
| Stay in SNS sandbox (verify each tester's phone) | Workable for closed beta; doesn't scale to public |
| Register a business and submit toll-free / 10DLC | Out of MVP scope (paperwork + cost) |
| **Drop phone verification at MVP** (this design) | **Chosen** — simplest path; preserves all other functionality |
| Email-only with phone added post-business-registration | Equivalent to chosen, but phrased as deferred-add-later |

The chosen path lets MVP launch on email-only auth without external dependencies, and reintroduces phone verification as a post-MVP feature once business registration completes.

### Why Cognito (not roll-your-own)

| Option | Pros | Cons |
|---|---|---|
| **Cognito User Pool (chosen)** | AWS-native; free tier 50k MAU; SRP password protocol; native API Gateway JWT authorizer; managed email verification via Cognito-managed sender or SES; OAuth federation when ready. | Some quirks with admin SDK. |
| Roll-your-own | Full control. | Months of work; not aligned with timeline. |
| Auth0 / Clerk / Supabase | Great DX. | Non-AWS; violates AWS Mandate. |

**Decision: Cognito User Pool.**

### Email verification path at MVP (no custom domain yet)

ContriCool runs at MVP on the AWS-default `cloudfront.net` domain (Designs 1, 3). We have no custom email-sending domain yet, so SES production access isn't requested at MVP.

- **Cognito email sender at MVP**: Cognito's managed sender (`no-reply@verificationemail.com`) handles email verification and forgot-password flows. Cognito limits this managed sender to ~50 emails/day per pool — well above MVP need (<10/day at <100 DAU).
- **Friendly-from name** is configurable in Cognito ("ContriCool ⟨no-reply@verificationemail.com⟩") to reduce phishing-vibes.
- **Switch to SES** when `contricool.com` registers: configure Cognito to use a verified SES identity (`noreply@mail.contricool.com`) with our own DKIM/SPF/DMARC. Higher deliverability, our brand, no Cognito daily cap.

### Signup Flow

```mermaid
sequenceDiagram
    participant C as Client (Expo web/native)
    participant CF as CloudFront
    participant API as Lambda (FastAPI)
    participant Cog as Cognito User Pool
    participant DDB as DDB ContriCool-Users
    participant Sender as Cognito-managed sender → SES

    C->>CF: POST /v1/auth/signup<br/>{email, password, name, currency, phone (optional)}
    CF->>API: forward
    API->>API: validate (email format, password strength,<br/>currency in {USD,INR}, phone E.164 if provided);<br/>generate user_id ULID
    API->>Cog: SignUp(username=email, password,<br/>attrs={email, name, custom:user_id, phone_number?})
    Cog->>Sender: verification email (code, 24h TTL)
    API-->>C: 202 {user_id, status: "PENDING_VERIFICATION"}

    C->>API: POST /v1/auth/verify-email {email, code}
    API->>Cog: ConfirmSignUp(username=email, code)
    Cog-->>API: ok (email_verified=true; account CONFIRMED)
    API->>DDB: PutItem USER#<user_id>#META<br/>{display_name, currency, status:"active",<br/>created_at,<br/>GSI1PK=EMAIL#hash(email)}
    DDB-->>API: ok
    API-->>C: 200 {email_verified: true, account_active: true}

    C->>API: POST /v1/auth/login {email, password}
    API->>Cog: InitiateAuth (USER_SRP_AUTH)
    Cog-->>API: SRP challenge → tokens (access, id, refresh)
    API->>DDB: GetItem USER#<user_id>#META (for user object: name, currency)
    DDB-->>API: user row
    API-->>C: 200 {tokens, user: {user_id, name, currency, phone (from ID token if present), ...}}
```

Implementation notes:

- **One verification step, one DDB write.** The META row is written once, atomically, after Cognito's `ConfirmSignUp` succeeds. Failed signups (email never verified) leave no DDB row at all — friend lookup correctly returns `USER_NOT_FOUND` for them. Account-active = email-verified = DDB row exists.
- **Idempotent retry**: post-`ConfirmSignUp` DDB write retries idempotently using the fixed `user_id`. A permanent failure is alarmed and surfaced for manual reconciliation.
- **`phone` is captured if provided** in the signup request and stored as an unverified `phone_number` Cognito attribute. We never validate ownership; UI can show "phone (unverified)" badge in settings if needed. Phone never lands in DynamoDB.
- **`currency`** is captured at signup, validated against the allowed enum (USD, INR at MVP), and written to DDB at the same time as the META row. Never goes through Cognito.
- **No phone verification step exists** in this flow. There is no `/v1/auth/verify-phone` endpoint. Cognito is configured with phone as optional + unverified.

### Login Flow

- **SRP (Secure Remote Password)** — password never traverses the network in plaintext. Amplify Auth on the client handles SRP with Cognito; backend never sees the password.
- On successful auth, Cognito returns ID token (JWT, 1h), access token (JWT, 1h), refresh token (opaque, 30d).
- Backend never holds these; the client stores them per-platform (see "Token Strategy" below).

### Token Strategy

| Token | Lifetime | Purpose | Web storage | Native storage |
|---|---|---|---|---|
| Access | 1 hour | Bearer for API Gateway authorizer | in-memory only | in-memory only |
| ID | 1 hour | Read user attributes client-side (incl. unverified phone, if present) | in-memory only | in-memory only |
| Refresh | 30 days | Mint new access + ID tokens | **HttpOnly Secure SameSite=Strict cookie** scoped to the CloudFront distribution domain (e.g., `d-prod.cloudfront.net`); never reaches JS | `expo-secure-store` (iOS Keychain / Android EncryptedSharedPreferences) — Amplify reads/writes via the secure-store adapter |

**Why HttpOnly cookie for refresh on web (not localStorage)**:

- localStorage is JS-readable — XSS pwns the long-lived token.
- HttpOnly cookie is unreachable from JS.
- Single CloudFront distribution per env (Design 1) means web and API are same-origin: cookie auto-attaches without `credentials: 'include'` cross-origin gymnastics.
- We accept the small backend cost: a `/v1/auth/refresh` endpoint that reads the cookie, calls Cognito's `InitiateAuth(REFRESH_TOKEN_AUTH)`, and returns a fresh access+ID token in the body.

```mermaid
sequenceDiagram
    participant C as Web client
    participant CF as CloudFront
    participant API as /v1/auth/refresh
    participant Cog as Cognito
    C->>CF: POST /v1/auth/refresh<br/>(cookie: rt=<refresh-token>)
    CF->>API: forward (cookie auto-attaches; same-origin)
    API->>Cog: InitiateAuth(REFRESH_TOKEN_AUTH, refresh)
    Cog-->>API: new access + id (refresh unchanged unless rotated)
    API-->>C: 200 {access, id} + Set-Cookie: rt=<same-or-rotated>
```

**Native (iOS/Android via Expo)**: Amplify Auth defaults to using `expo-secure-store` when the package is installed. The refresh token never crosses our backend; Amplify calls Cognito's `InitiateAuth(REFRESH_TOKEN_AUTH)` directly.

### Account Recovery

- **Forgot password**: standard Cognito `ForgotPassword(email)` → email link with code → `ConfirmForgotPassword`. Implemented as `POST /v1/auth/forgot-password` and `POST /v1/auth/reset-password`. Email goes via Cognito-managed sender at MVP.
- **Lost email access**: not supported at MVP. Manual support intervention (rare; document in pre-launch runbook).
- **Email change**: post-MVP feature. Requires re-verification.
- **Phone**: capture/update is supported via `PATCH /v1/me` (writes to Cognito's optional phone_number attribute). No verification at MVP; UI shows "unverified" badge.
- **Account deletion**: see Design 13.

### MFA Stance

- **MVP**: passwords + verified email. **No MFA** — solo-dev MVP, friend-circle scope.
- **Post-MVP**: optional TOTP MFA via authenticator app (Cognito supports). SMS-MFA explicitly avoided (SS7 risk + currently no SMS-sending capability).

### Federation (Google, Apple, etc.)

- **Deferred.** Cognito supports OIDC/SAML federation; we'll wire it later via Cognito hosted UI. Data model (ULID-as-user-id, custom:user_id attribute) is already federation-friendly.

### SMS Delivery

**Not used at MVP.** No production code path sends SMS. Cognito is configured with email-only verification. The SNS SMS account-level monthly spend limit ($5) remains in place purely as defense-in-depth.

When phone verification is reintroduced post-MVP, this section gets rewritten with originator (10DLC / toll-free) wiring and DLT registration for India. Until then, every section in the design that previously discussed SMS routing or DLT is moot.

### Identity Store of Record

- **Cognito** holds: email, password hash, name, **`custom:user_id`** (only custom attribute), and optionally phone_number (unverified).
- **DynamoDB `ContriCool-Users-<env>`** holds: profile (display_name, currency, status, created_at), friendships, email lookup-hash on GSI1, OTP rate-limit rows. **Phone is not stored in DDB at all.** Joined to Cognito via the `custom:user_id` ULID.
- **Cognito = source of truth for identity (who you are + how you authenticate).**
- **DynamoDB = source of truth for app data, including all user preferences (currency now; locale, theme, notification prefs later).**

## Component / Low-Level Design

### Backend `auth/` feature module

```
apps/api/app/features/auth/
  __init__.py
  routes.py            # FastAPI router
  service.py           # business logic: signup, verify-email, login, refresh, forgot, reset
  models.py            # Pydantic request/response models
  cognito_client.py    # boto3 wrapper, retries, error mapping
  rate_limit.py        # per-identity OTP rate-limit using ContriCool-Users-<env> DDB
  README.md
```

Endpoints (full contract in Design 8):

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/auth/signup | Start signup; returns user_id and PENDING_VERIFICATION |
| POST | /v1/auth/verify-email | Confirm email with code; activates account |
| POST | /v1/auth/resend-email-code | Rate-limited resend |
| POST | /v1/auth/login | SRP auth, returns access+id, sets refresh cookie (web) |
| POST | /v1/auth/refresh | (web only) reads refresh cookie, returns fresh access+id |
| POST | /v1/auth/logout | Revoke refresh token + clear cookie |
| POST | /v1/auth/forgot-password | Sends reset code via email |
| POST | /v1/auth/reset-password | Confirms reset with code |

**Removed from earlier designs (no longer exist):** `/v1/auth/verify-phone`, `/v1/auth/resend-phone-code`.

### API Gateway JWT Authorizer

- API Gateway HTTP API has a built-in JWT authorizer pointed at Cognito (`https://cognito-idp.us-west-2.amazonaws.com/<userPoolId>/.well-known/openid-configuration`).
- Verifies signature, expiry, audience (= app client ID), and issuer.
- Injects `claims` into the Lambda event under `event.requestContext.authorizer.jwt.claims` — Lambda code reads `custom:user_id` from there, never trusts the request body for identity.
- All `/v1/*` routes require auth **except**: `/v1/auth/signup`, `/v1/auth/login`, `/v1/auth/verify-email`, `/v1/auth/refresh`, `/v1/auth/forgot-password`, `/v1/auth/reset-password`, `/v1/auth/resend-email-code`, `/v1/health`, `/v1/telemetry/error`.

### Rate-limiting OTP requests

In `ContriCool-Users-<env>`:

```
PK: AUTH_RATE#<sha256(salt+lower(email))>
SK: OTP#EMAIL              # only EMAIL channel exists at MVP; SK shape forward-compatible for OTP#SMS later
attempts_hour: number
hour_window_started_at: timestamp
attempts_day: number
day_window_started_at: timestamp
ttl: now + 24h             # DDB TTL auto-cleans
```

Caps at MVP: **5 email-OTP requests / hour**, **20 / day** per email identity.

On each OTP request, conditionally increment counters; reject when above caps.

### Client (Expo + Amplify Auth v6)

- One Cognito App Client **per platform**, all writing to the same user pool — accounts shared across web, iOS, Android.
- Web app client: `VITE_USER_POOL_CLIENT_ID_WEB`. Native app clients: `IOS_CLIENT_ID`, `ANDROID_CLIENT_ID`. All public clients (no secret).
- Amplify config (single `apps/client/lib/auth.ts`):
  ```ts
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: env.userPoolId,
        userPoolClientId: env.userPoolClientId,
        loginWith: { email: true },
      },
    },
  });
  ```
- **Refresh-token storage strategy by platform**:
  - **Web**: refresh token never reaches the client. Custom Amplify storage adapter throws on refresh-token writes; backend `/v1/auth/refresh` cookie path handles it.
  - **Native (iOS/Android)**: `expo-secure-store` (Keychain / EncryptedSharedPreferences). Amplify auto-detects when the package is installed.
- API client (`packages/client-sdk`) intercepts:
  - Every request: attaches `Authorization: Bearer <accessToken>` from Amplify in-memory.
  - On 401:
    - Web: calls `/v1/auth/refresh`, stores returned tokens, retries the original request once.
    - Native: calls Amplify's `fetchAuthSession({ forceRefresh: true })`, retries.
  - On second 401: triggers Amplify sign-out; navigates to `/login`.

### Cognito App Clients summary

| Client | Platform | Secret | Allowed flows | Refresh-token validity |
|---|---|---|---|---|
| `web` | web | no | USER_SRP_AUTH, REFRESH_TOKEN_AUTH | 30d |
| `ios` | iOS app | no | USER_SRP_AUTH, REFRESH_TOKEN_AUTH | 30d |
| `android` | Android app | no | USER_SRP_AUTH, REFRESH_TOKEN_AUTH | 30d |

## Security Considerations

- **Password hashing**: handled by Cognito (Argon2id by default).
- **PII in logs**: `email` and `phone` are PII — Powertools Logger denylist must include them. Code review enforces.
- **Phone is unverified** — the UI must clearly display "(unverified)" beside any user-supplied phone. Server treats phone as user-claimed metadata, never as proof of identity.
- **Brute force**: Cognito has built-in lockout; we layer API Gateway throttling on `/login` (~5/s) and our own rate-limit on `/auth/*` (~10 attempts/15 min/IP).
- **CSRF for refresh-token cookie**: SameSite=Strict + same-origin keeps it mitigated. Optionally add a CSRF double-submit token on `/v1/auth/refresh` if we adopt cross-origin scenarios later.
- **Token leakage**: access token in `Authorization` header (not URL). Logs never record headers.
- **Lost device**: user can call `/v1/auth/logout` (revokes refresh tokens in Cognito), then change password — invalidates all old refresh tokens.
- **Cognito User Pool encryption**: Cognito-managed key (Cognito CMK requires Advanced Security mode at $0.05/MAU — defer).

## Open Questions

1. **Email verification UX** — single-page code-input form (default) vs link-based magic-link flow? Recommendation: code-input for MVP (works everywhere, no deep-linking complexity).
2. **Email-as-username** confirmed; no separate username.
3. **Cognito hosted UI**: defer; custom Expo forms give the friction-free signup we need; hosted UI is for federation flows we're not adding yet.
4. **Custom domain for Cognito email sender**: switch from Cognito-managed to SES with `noreply@mail.contricool.com` once `contricool.com` is registered (Phase 7-or-later).
5. **Re-introduction of phone verification post-MVP**: tracked in CONSTRAINTS.md "Path to re-introduce phone verification" — requires business registration + originator (10DLC/toll-free or Indian DLT sender ID) + GSI2 backfill.

## Summary

- **Email is the sole required + verified identity factor** at MVP. Phone is optional unverified Cognito metadata, never stored in DynamoDB, never used for search/recovery/auth.
- **Cognito User Pool** is the identity store; `custom:user_id` ULID is the only custom attribute. All preferences (currency, future locale/theme) live exclusively in DDB.
- **Email verification at MVP via Cognito-managed sender** (no SES production access, no custom domain); switch to SES when `contricool.com` registers.
- **JWT sessions**: 1h access/ID, 30d refresh. Web stores refresh in HttpOnly cookie via `/v1/auth/refresh`; native stores in `expo-secure-store`.
- **No SMS at MVP** — no production code path publishes SMS; SNS SMS spend cap stays at $5/mo as defense-in-depth.
- **Three Cognito app clients** (web, iOS, Android) all writing to the same user pool — accounts shared seamlessly across platforms; phone verification reintroduced post-business-registration.
