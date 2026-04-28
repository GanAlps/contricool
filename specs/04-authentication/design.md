# ContriCool — Authentication Design

## Overview

This design fixes how users prove identity in ContriCool: signup, verify email + phone, sign in, refresh tokens, and recover access. Design level: **HLD + LLD**. Headlines: **Cognito User Pool** with both email and phone as required+verified attributes; **Cognito-managed email sender at MVP** (no custom domain yet); **password + email/phone verification at signup**; **JWT-based sessions with 1-hour access tokens and 30-day refresh tokens**; **AWS Amplify Auth (v6) on the Expo client** doing SRP, refresh, and platform-secure storage transparently. Web stores the refresh token in an **HttpOnly cookie scoped to the CloudFront distribution domain** via a backend `/v1/auth/refresh` proxy; native uses `expo-secure-store` (Keychain/EncryptedSharedPreferences). Federation (Google/Apple) is deferred.

## Authentication Design

### Identity model

- **One Cognito User Pool per environment** (`contricool-dev`, `contricool-prod`).
- **Cognito holds identity only** — preferences/settings live in DynamoDB.
- Cognito attributes:
  - `email` — standard, verified.
  - `phone_number` — standard, verified (E.164).
  - `name` — standard, mutable.
  - `custom:user_id` — application-level ULID, generated server-side at signup, written into Cognito on confirmation. App data in DynamoDB keys by this ULID, not by Cognito's `sub`. Portable across IdP migrations and easier in logs. **This is the only custom attribute** — it's an identity binding to our app's user record.
- **Currency** (and any future user setting like locale, theme, notification prefs) lives **only in `ContriCool-Users-<env>` on `USER#<id>#META`**, never in Cognito. Reasons:
  - Currency is preference data, not identity data; Cognito's job is authentication.
  - Cognito custom attributes can't be renamed or removed once created.
  - Each Cognito custom attribute inflates every JWT for the user's lifetime.
  - Updating Cognito attributes is slower (`AdminUpdateUserAttributes`) than a DDB `UpdateItem`.
  - Mirroring app data into Cognito risks drift; single-source-of-truth in DDB removes the hazard.
  - The "save a DDB read" argument is mostly imaginary — most authenticated requests touch DDB for the resource being accessed anyway.
- **Username**: Cognito's auto-generated `sub` (UUID); we never expose it. Sign-in uses `email`.
- **Password policy**: min 10 chars, ≥1 number, ≥1 lowercase, ≥1 uppercase, ≥1 symbol; password history 3.
- **Account states**: `UNCONFIRMED` → `CONFIRMED` (email verified) → `CONFIRMED + phone_number_verified=true`. Sign-in is allowed only when both verifications complete; the API enforces this in addition to Cognito.

### Why Cognito (not roll-your-own)

| Option | Pros | Cons |
|---|---|---|
| **Cognito User Pool (chosen)** | AWS-native; free tier 50k MAU; SRP; native API Gateway JWT authorizer; managed email/SMS verification; optional MFA; OAuth federation when ready. | Some quirks with admin SDK; SMS via SNS (paid, India needs DLT). |
| Roll-your-own | Full control. | Months of work; not aligned with timeline. |
| Auth0 / Clerk / Supabase | Great DX. | Non-AWS; violates AWS Mandate. |

**Decision: Cognito User Pool.**

### Email verification path at MVP (no custom domain yet)

ContriCool runs at MVP on the AWS-default `cloudfront.net` domain (Designs 1, 3). We have no custom email-sending domain yet, so SES production access isn't requested at MVP.

- **Cognito email sender at MVP**: Cognito's managed sender (`no-reply@verificationemail.com`) handles email verification, account confirmation, and forgot-password flows. Cognito limits this managed sender to ~50 emails/day per pool — well above MVP need (<10/day at <100 DAU).
- **Friendly-from name** is configurable in Cognito ("ContriCool ⟨no-reply@verificationemail.com⟩") to reduce phishing-vibes.
- **Switch to SES** when `contricool.com` registers: configure Cognito to use a verified SES identity (`noreply@mail.contricool.com`) with our own DKIM/SPF/DMARC. Higher deliverability, our brand, no Cognito daily cap.

### Signup Flow

User constraint: **both email AND phone required + verified before account is active**.

```mermaid
sequenceDiagram
    participant C as Client (Expo web/native)
    participant CF as CloudFront
    participant API as Lambda (FastAPI)
    participant Cog as Cognito User Pool
    participant DDB as DDB ContriCool-Users
    participant Sender as Cognito-managed sender → SES
    participant SNS as SNS (SMS)

    C->>CF: POST /v1/auth/signup<br/>{email, phone, password, name, currency}
    CF->>API: forward
    API->>API: validate (E.164 phone, currency in {USD,INR}); generate user_id ULID
    API->>Cog: SignUp(username=email, password,<br/>attrs={email, phone_number, name, custom:user_id})
    Cog->>Sender: verification email (code, 24h TTL)
    API->>Cog: GetUserAttributeVerificationCode(phone_number) [admin]
    Cog->>SNS: SMS OTP to phone (10 min TTL)
    API-->>C: 202 {user_id, status: "PENDING_VERIFICATION"}

    C->>API: POST /v1/auth/verify-email {email, code}
    API->>Cog: ConfirmSignUp(username=email, code)
    Cog-->>API: ok (email_verified=true; account CONFIRMED)
    API-->>C: 200 {email_verified: true}

    C->>API: POST /v1/auth/verify-phone {email, code}
    API->>Cog: AdminConfirmUserAttribute(phone_number, code)
    Cog-->>API: ok
    API->>DDB: PutItem USER#<user_id>#META<br/>{display_name, currency, status:"active",<br/>created_at,<br/>GSI1PK=EMAIL#hash, GSI2PK=PHONE#hash}
    DDB-->>API: ok
    API-->>C: 200 {email_verified: true, phone_verified: true, account_active: true}

    C->>API: POST /v1/auth/login {email, password}
    API->>Cog: InitiateAuth (USER_SRP_AUTH)
    Cog-->>API: SRP challenge → tokens (access, id, refresh)
    API->>DDB: GetItem USER#<user_id>#META (for user object: name, currency)
    DDB-->>API: user row
    API-->>C: 200 {tokens, user: {user_id, name, currency, ...}}
```

Implementation notes:

- We trigger the SMS code separately via `GetUserAttributeVerificationCode` (after the user is `CONFIRMED` via email). UI shows both code inputs in parallel with "resend" buttons.
- "Resend" rate-limited at the API layer to **3/hour per identity** to control SMS spend (rate-limit rows live in `ContriCool-Users-<env>` table; see Design 7).
- **The DDB `USER#<id>#META` row is written once, atomically, only after BOTH email and phone verifications complete** — i.e., at the end of the `verify-phone` step. This means:
  - Users who only verify email (and never phone) have no DDB row at all — they remain Cognito-only with no app data, and the friend-lookup endpoints correctly return `USER_NOT_FOUND` for them. This matches the rule that account isn't active until both verifications are done.
  - The META row carries `GSI1PK=EMAIL#<hash>` and `GSI2PK=PHONE#<hash>` directly — both lookup indexes are populated atomically from the same write. No second-row pivot, no race window between email-hash and phone-hash availability.
  - If the DDB write fails post-`AdminConfirmUserAttribute`, the API retries idempotently (user_id is fixed). A permanent failure is alarmed and surfaced for manual reconciliation; rare, but the recovery is to re-call with the same user_id.
- `currency` is captured at signup, stored in the API's signup request payload, and written into DDB at the same time as the meta row. It never goes through Cognito.

### Login Flow

- **SRP (Secure Remote Password)** — password never traverses the network in plaintext. Amplify Auth on the client handles SRP with Cognito; backend never sees the password.
- On successful auth, Cognito returns ID token (JWT, 1h), access token (JWT, 1h), refresh token (opaque, 30d).
- Backend never holds these; the client stores them per-platform (see "Token Strategy" below).

### Token Strategy

| Token | Lifetime | Purpose | Web storage | Native storage |
|---|---|---|---|---|
| Access | 1 hour | Bearer for API Gateway authorizer | in-memory only | in-memory only |
| ID | 1 hour | Read user attributes client-side | in-memory only | in-memory only |
| Refresh | 30 days | Mint new access + ID tokens | **HttpOnly Secure SameSite=Strict cookie** scoped to the CloudFront distribution domain (e.g., `d-prod.cloudfront.net`); never reaches JS | `expo-secure-store` (iOS Keychain / Android EncryptedSharedPreferences) — Amplify reads/writes via the secure-store adapter |

**Why HttpOnly cookie for refresh on web (not localStorage)**:

- localStorage is JS-readable — XSS pwns the long-lived token.
- HttpOnly cookie is unreachable from JS.
- Single CloudFront distribution per env (Design 1) means web and API are same-origin: cookie auto-attaches without `credentials: 'include'` cross-origin gymnastics.
- We accept the small backend cost: a `/v1/auth/refresh` endpoint that reads the cookie, calls Cognito's `InitiateAuth(REFRESH_TOKEN_AUTH)`, and returns a fresh access+ID token in the body. The cookie is scoped to the CloudFront domain (`d-<id>.cloudfront.net` at MVP, later `contricool.com` once registered — domain switch handled by setting the cookie domain dynamically based on `Host` header).

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

**Native (iOS/Android via Expo)**: Amplify Auth defaults to using `expo-secure-store` when the package is installed. The refresh token never crosses our backend; Amplify calls Cognito's `InitiateAuth(REFRESH_TOKEN_AUTH)` directly. No `/v1/auth/refresh` proxy on native.

### Account Recovery

- **Forgot password**: standard Cognito `ForgotPassword(email)` → email link with code → `ConfirmForgotPassword`. Implemented as `POST /v1/auth/forgot-password` and `POST /v1/auth/reset-password`. Email goes via Cognito-managed sender at MVP.
- **Forgot phone**: not supported in MVP. Phone is a verification channel as well as identifier; changing it is sensitive. Manual support intervention.
- **Email change / phone change**: post-MVP feature. Requires re-verification.
- **Account deletion**: see Design 13.

### MFA Stance

- **MVP**: passwords + verified email/phone. **No mandatory MFA** — adds friction for a friend-circle MVP.
- **Post-MVP**: optional TOTP MFA (Cognito supports). SMS-MFA explicitly avoided (SS7 risk).

### Federation (Google, Apple, etc.)

- **Deferred.** Cognito supports OIDC/SAML federation; we'll wire it later via Cognito hosted UI. Data model (ULID-as-user-id, custom:user_id attribute) is already federation-friendly.

### SMS Delivery

- **SNS direct SMS** (not Pinpoint) at MVP — simpler IAM, sufficient for OTP.
- **Originating numbers**:
  - **US**: 10DLC long code (~$1/mo + per-msg fees) — register via SNS Origination Numbers console.
  - **India**: Sender ID `CONTRICOOL` registered via DLT (TRAI). Without DLT, delivery is unreliable. **Start DLT registration in parallel with implementation.** Until DLT clears, accept patchy India SMS deliverability.
- **Spend cap**: SNS account-level monthly spend limit **`$5`** at MVP (raise via Service Quotas request once real volume justifies it). Combined with the per-identity OTP rate limit (3/h, 10/day SMS), $5 covers ~125 India SMS or ~775 US SMS per month — comfortably above MVP traffic.
- **Rate limit per identity** (rows in `ContriCool-Users-<env>` table): OTP request 3/hour, 10/day.

### Identity Store of Record

- **Cognito** holds: email, phone_number, password hash, name, **`custom:user_id`** (the only custom attribute — an identity binding to our DDB user record).
- **DynamoDB `ContriCool-Users-<env>`** holds: **profile (display_name, currency, status, created_at)**, friendships, lookup hashes, OTP rate-limit rows. Joined to Cognito via the `custom:user_id` ULID written into Cognito at SignUp and used as the DDB `USER#<id>` partition key.
- **Cognito = source of truth for identity (who you are + how you authenticate). DynamoDB = source of truth for app data, including all user preferences (currency now; locale, theme, notification prefs later).**

## Component / Low-Level Design

### Backend `auth/` feature module

```
apps/api/app/features/auth/
  __init__.py
  routes.py            # FastAPI router
  service.py           # business logic: signup, verify, login, refresh, forgot
  models.py            # Pydantic request/response models
  cognito_client.py    # boto3 wrapper, retries, error mapping
  rate_limit.py        # OTP-rate-limit using ContriCool-Users-<env> DDB
  README.md
```

Endpoints (full contract in Design 8):

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/auth/signup | Start signup; returns user_id and PENDING_VERIFICATION |
| POST | /v1/auth/verify-email | Confirm email with code |
| POST | /v1/auth/verify-phone | Confirm phone with code |
| POST | /v1/auth/resend-email-code | Rate-limited |
| POST | /v1/auth/resend-phone-code | Rate-limited |
| POST | /v1/auth/login | SRP auth, returns access+id, sets refresh cookie (web) |
| POST | /v1/auth/refresh | (web only) reads refresh cookie, returns fresh access+id |
| POST | /v1/auth/logout | Revoke refresh token + clear cookie |
| POST | /v1/auth/forgot-password | Sends reset code |
| POST | /v1/auth/reset-password | Confirms reset with code |

### API Gateway JWT Authorizer

- API Gateway HTTP API has a built-in JWT authorizer pointed at Cognito (`https://cognito-idp.us-west-2.amazonaws.com/<userPoolId>/.well-known/openid-configuration`).
- Verifies signature, expiry, audience (= app client ID), and issuer.
- Injects `claims` into the Lambda event under `event.requestContext.authorizer.jwt.claims` — Lambda code reads `custom:user_id` from there, never trusts the request body for identity.
- All `/v1/*` routes require auth **except**: `/v1/auth/signup`, `/v1/auth/login`, `/v1/auth/verify-email`, `/v1/auth/verify-phone`, `/v1/auth/refresh`, `/v1/auth/forgot-password`, `/v1/auth/reset-password`, `/v1/auth/resend-*`, `/v1/health`, `/v1/telemetry/error`.

### Rate-limiting OTP requests

In `ContriCool-Users-<env>`:

```
PK: RATE#<sha256(salt+lower(identity))>
SK: OTP#<channel>          # OTP_EMAIL or OTP_SMS
attempts_hour: number
hour_window_started_at: timestamp
attempts_day: number
day_window_started_at: timestamp
ttl: now + 24h             # DDB TTL auto-cleans
```

On each OTP request, conditionally increment counters; reject when above caps.

### Client (Expo + Amplify Auth v6)

- One Cognito App Client **per platform**, all writing to the same user pool — accounts shared across web, iOS, Android. App clients differ in refresh-token validity and (post-MVP) OAuth secrets.
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
- **Refresh-token storage strategy by platform** (configured at app boot):
  - **Web** (Platform.OS === 'web'): override Amplify storage to a `KeyValueStorage` adapter that throws on refresh-token writes; rely on the backend `/v1/auth/refresh` cookie path. Amplify still keeps access + ID tokens in memory.
  - **Native** (iOS/Android): Amplify defaults to `expo-secure-store` (auto-detected when the package is installed). No backend proxy needed.
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

Future server-to-server (admin tools): client_credentials with secret, separate scopes — when needed.

## Security Considerations

- **Password hashing**: handled by Cognito (Argon2id by default).
- **PII in logs**: `email` and `phone` are PII — Powertools Logger denylist must include them. Code review enforces.
- **Brute force**: Cognito has built-in lockout; we layer API Gateway throttling on `/login` (~5/s) and our own rate-limit on `/auth/*` (~10 attempts/15 min/IP).
- **CSRF for refresh-token cookie**: SameSite=Strict + same-origin (single CloudFront distribution) keeps it mitigated. Optionally add a CSRF double-submit token on `/v1/auth/refresh` if we adopt cross-origin scenarios later.
- **Token leakage**: access token in `Authorization` header (not URL). Logs never record headers.
- **Lost device**: user can call `/v1/auth/logout` (revokes refresh tokens in Cognito), then change password — invalidates all old refresh tokens.
- **Cognito User Pool encryption**: Cognito-managed key (Cognito CMK requires Advanced Security mode at $0.05/MAU — defer).

## Open Questions

1. **Single-page verify UX**: two-code inputs on one page (recommended) vs sequential pages — UI design (Design 10).
2. **Email-as-username** confirmed; no separate username.
3. **Cognito hosted UI**: defer; custom Expo forms give the friction-free signup we need; hosted UI is for federation flows we're not adding yet.
4. **DLT registration for India SMS** — non-trivial process (~1–3 weeks). Started in parallel with implementation; if not done by launch, accept patchy India SMS delivery; voice OTP via Pinpoint as a future enhancement.
5. **Custom domain for Cognito email sender**: switch from Cognito-managed to SES with `noreply@mail.contricool.com` once `contricool.com` is registered.

## Summary

- **Cognito User Pool** is the identity store; `email` + `phone_number` both required and verified before account activation; `custom:user_id` ULID is the only custom attribute and joins to DynamoDB `ContriCool-Users-<env>`. **All user preferences (currency, future locale/theme) live exclusively in DDB**, not Cognito.
- **Email verification at MVP via Cognito-managed sender** (no SES production access, no custom domain); switch to SES when `contricool.com` registers.
- **Signup is two-step verify** (email code, then phone OTP), both rate-limited at the API layer to control SMS cost.
- **JWT sessions**: 1h access/ID, 30d refresh. **Web stores refresh in HttpOnly cookie** scoped to the CloudFront distribution domain via `/v1/auth/refresh`; **native stores it in `expo-secure-store`** (Keychain/EncryptedSharedPreferences) — Amplify handles both transparently.
- **API Gateway JWT authorizer** does signature/expiry/issuer/audience validation at the edge; Lambda reads `custom:user_id` from `requestContext.authorizer.jwt.claims` and trusts that for identity.
- **Three Cognito app clients** (web, iOS, Android) all writing to the same user pool — accounts shared seamlessly across platforms.
