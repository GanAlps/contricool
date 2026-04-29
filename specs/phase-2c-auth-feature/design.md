# Phase 2c — Auth Feature Backend — Design

**Complexity: COMPLEX** — eight endpoints, two new subsystems (JWT
verifier + rate-limiter), CDK changes (JWT authorizer wiring, IAM
grants), and a large negative-test surface.

## Overview

Phase 2c implements the email-only auth backend. The design solves five
distinct concerns:

1. **Edge auth** — API Gateway HTTP API JWT authorizer rejects bad tokens
   before invoking Lambda.
2. **App auth** — `current_principal()` FastAPI dependency re-verifies
   tokens inside Lambda for defense in depth and clean handler ergonomics.
3. **Cognito client** — a thin boto3 wrapper that maps Cognito exceptions
   to the project's stable error envelope and never leaks PII.
4. **OTP rate-limiter** — DDB-backed dual-window (hour/day) counter with
   conditional updates so concurrent calls can't race past the cap.
5. **Cookie + idempotency** — HttpOnly refresh-token cookie set on
   login, cleared on logout/refresh-failure; Idempotency-Key on signup
   via Powertools.

## High-Level Design

### System view (Phase 2c additions in **bold**)

```mermaid
graph TB
    Client[Web/Native Client]
    CF[CloudFront]
    APIG[API Gateway HTTP API]
    Auth[**JWT Authorizer**<br/>Cognito issuer + 3 client IDs]
    Lambda[FastAPI Lambda]
    Cog[Cognito User Pool]
    DDB[(ContriCool-Users-env)]
    SSM[SSM Parameter Store]

    Client -->|HTTPS| CF
    CF -->|/v1/*| APIG
    APIG --> Auth
    Auth -->|valid JWT or<br/>auth=NONE route| Lambda
    Lambda -.->|cold start| SSM
    Lambda -->|**current_principal()**<br/>**re-verifies JWT**| Lambda
    Lambda -->|signup/confirm/<br/>login/refresh/<br/>logout/forgot/reset| Cog
    Lambda -->|RATE rows<br/>USER META rows| DDB
```

### Per-endpoint flow summary

| Endpoint | API GW auth | Cognito call | DDB write | Cookie |
|---|---|---|---|---|
| POST /v1/auth/signup | none | `SignUp` | none | none |
| POST /v1/auth/verify-email | none | `ConfirmSignUp` + `AdminGetUser` | `PutItem USER#…#META` (cond) | none |
| POST /v1/auth/resend-email-code | none | `ResendConfirmationCode` | `UpdateItem AUTH_RATE#…` | none |
| POST /v1/auth/login | none | `InitiateAuth(USER_PASSWORD_AUTH)` | `GetItem USER#…#META` | **set rt** |
| POST /v1/auth/refresh | none | `InitiateAuth(REFRESH_TOKEN_AUTH)` | none | **read rt; clear on fail** |
| POST /v1/auth/logout | **JWT** | `GlobalSignOut` | none | **clear rt** |
| POST /v1/auth/forgot-password | none | `ForgotPassword` | `UpdateItem AUTH_RATE#…` | none |
| POST /v1/auth/reset-password | none | `ConfirmForgotPassword` | none | none |

### Signup → Verify → Login flow

```mermaid
sequenceDiagram
    participant C as Client
    participant API as Lambda
    participant Cog as Cognito
    participant DDB as ContriCool-Users

    C->>API: POST /v1/auth/signup<br/>{email,password,name,currency,phone?}
    API->>API: validate; user_id = ULID()
    API->>Cog: SignUp(email, password, attrs={email,name,custom:user_id,phone?})
    Cog-->>API: UserSub (Cognito's UUID — discarded)
    Cog-->>C: email with 6-digit code (managed sender)
    API-->>C: 202 {user_id, status:"PENDING_VERIFICATION"}

    C->>API: POST /v1/auth/verify-email {email,code}
    API->>Cog: ConfirmSignUp(email, code)
    Cog-->>API: ok
    API->>Cog: AdminGetUser(email) → custom:user_id, email
    API->>DDB: PutItem USER#<user_id>#META (cond: attribute_not_exists)<br/>{display_name, currency, status:"active",<br/> created_at, GSI1PK=EMAIL#hash, GSI1SK=USER#…}
    API-->>C: 200 {email_verified:true, account_active:true}

    C->>API: POST /v1/auth/login {email,password}
    API->>Cog: InitiateAuth(USER_PASSWORD_AUTH, {USERNAME,PASSWORD})
    Cog-->>API: {access, id, refresh}
    API->>DDB: GetItem USER#<user_id>#META
    API-->>C: 200 {access_token, id_token, expires_in, user:{user_id,name,currency}}<br/>Set-Cookie: rt=…; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth
```

## Module Layout

```
apps/api/app/
├── core/
│   ├── security.py           # NEW — JWT verifier + JWKs cache
│   └── dependencies.py       # NEW — current_principal() FastAPI dep
└── features/
    └── auth/                 # NEW — feature module
        ├── __init__.py
        ├── routes.py         # FastAPI router @ /v1/auth
        ├── service.py        # business logic
        ├── models.py         # Pydantic v2 request/response models
        ├── cognito_client.py # boto3 wrapper + error mapping
        ├── rate_limit.py     # DDB conditional-update rate-limiter
        ├── errors.py         # AuthError exception + envelope shape
        └── README.md         # feature doc
```

## Component Design

### `app/core/security.py` — JWT verifier

```python
class JwtVerifier:
    """Verify a Cognito JWT using cached JWKs.

    Cache lifetime = cold-start lifetime. On a kid miss we refetch once
    (cheap insurance against Cognito key rotation).
    """

    def __init__(self, *, issuer: str, audience_ids: list[str]) -> None: ...

    def verify(self, token: str) -> dict[str, object]:
        """Return validated claims dict, or raise InvalidTokenError."""
```

Implementation:

- Library: **`pyjwt[crypto]`** with `PyJWKClient`. Mature, no native deps
  beyond `cryptography` (already in many transitive trees), lightweight,
  active.
- Why not `aws-jwt-verify`? It's a JS library only.
- Why not `python-jose`? Unmaintained since 2022; CVE history.
- Why not `aws-lambda-powertools`? Powertools v3 doesn't ship a JWT verifier.
- Verification steps:
  1. Decode header, read `kid`.
  2. Fetch signing key from `PyJWKClient(jwks_url)` — first call hits
     Cognito's `.well-known/jwks.json`, subsequent calls cached.
  3. `jwt.decode(token, signing_key, algorithms=["RS256"], options={
     "verify_aud": False  # Cognito access tokens use client_id
     })`. We do `aud` and `client_id` validation manually because
     access tokens vs ID tokens differ.
  4. Validate `iss` exactly equals issuer.
  5. Validate `token_use ∈ {"id", "access"}`.
  6. For `id` tokens: `aud` must be in `audience_ids`.
  7. For `access` tokens: `client_id` must be in `audience_ids`.
  8. `exp` is checked by `pyjwt` automatically.
- Cache: `JwtVerifier` is instantiated **once** at module scope when
  `dependencies.py` is imported, after `config.load()` has populated
  `cognito_user_pool_id` and the three client IDs. Test hooks reset the
  module global.

### `app/core/dependencies.py` — `current_principal()`

```python
async def current_principal(
    request: Request,
    verifier: JwtVerifier = Depends(_get_verifier),
) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise UnauthenticatedError()
    token = auth[7:].strip()
    try:
        claims = verifier.verify(token)
    except InvalidTokenError:
        raise UnauthenticatedError()
    return Principal.from_claims(claims)
```

`UnauthenticatedError` is converted to a 401 envelope by the global
exception handler (see `errors.py`).

### `app/features/auth/cognito_client.py`

A thin boto3 wrapper that:

- Constructs the `cognito-idp` client once at module scope (read-only
  in handler hot path).
- Maps Cognito exceptions to `AuthError(code, http_status, detail)`
  instances.
- Normalises usernames to `email.lower().strip()` before every call (the
  pool is configured `sign_in_case_sensitive=False`, but we double-check
  to keep tests deterministic).
- **Never logs the email** — handlers log `{event: "...", cognito_error_type:
  type(e).__name__}` when a Cognito error fires; cognito_client itself
  is silent.

```python
class CognitoClient:
    def sign_up(self, email: str, password: str, attrs: dict[str, str]) -> str: ...
    def confirm_sign_up(self, email: str, code: str) -> None: ...
    def admin_get_user(self, email: str) -> dict[str, str]: ...
    def resend_confirmation_code(self, email: str) -> None: ...
    def initiate_auth_user_password(self, email: str, password: str, client_id: str) -> dict: ...
    def initiate_auth_refresh(self, refresh_token: str, client_id: str) -> dict: ...
    def global_sign_out(self, access_token: str) -> None: ...
    def forgot_password(self, email: str) -> None: ...
    def confirm_forgot_password(self, email: str, code: str, password: str) -> None: ...
```

Error map (Cognito boto3 exception name → `AuthError` code):

| Cognito | code | HTTP |
|---|---|---|
| `UsernameExistsException` | `EMAIL_EXISTS` | 409 |
| `InvalidPasswordException` | `INVALID_PASSWORD` | 422 |
| `CodeMismatchException` | `INVALID_CODE` | 401 |
| `ExpiredCodeException` | `INVALID_CODE` | 401 |
| `UserNotConfirmedException` | `ACCOUNT_NOT_ACTIVE` | 403 |
| `PasswordResetRequiredException` | `PASSWORD_RESET_REQUIRED` | 403 |
| `NotAuthorizedException` (login path) | `INVALID_CREDENTIALS` | 401 |
| `NotAuthorizedException` (refresh/logout path) | `UNAUTHENTICATED` | 401 |
| `UserNotFoundException` (verify-email) | `USER_NOT_FOUND` | 404 |
| `UserNotFoundException` (login/forgot/reset) | masked → see per-endpoint rule | varies |
| `LimitExceededException` | `RATE_LIMITED` | 429 |
| `TooManyRequestsException` | `RATE_LIMITED` | 429 |
| `InvalidParameterException` (already confirmed) | `ALREADY_CONFIRMED` | 409 |

The `NotAuthorizedException` mapping is path-dependent because Cognito
re-uses the same exception for "wrong password" and "user disabled" and
"refresh token revoked" — the calling site decides which.

### `app/features/auth/rate_limit.py`

```python
class RateLimitExceeded(Exception):
    retry_after_seconds: int

def consume_otp_email(email: str) -> None:
    """Increment the OTP email counter; raise if over cap.

    Atomic conditional UpdateItem on ContriCool-Users-<env>:
      PK=AUTH_RATE#<sha256(salt|lower(email))>
      SK=OTP#EMAIL
    Attributes: attempts_hour, hour_window_started_at,
                attempts_day, day_window_started_at, ttl
    Caps: 5/hour, 20/day.
    """
```

Implementation strategy:

```
UpdateItem with ConditionExpression:
  attempts_hour < :hour_cap  AND  attempts_day < :day_cap
  OR hour_window_started_at < :hour_ago  -- stale window
  OR attribute_not_exists(PK)            -- first-ever request

UpdateExpression:
  SET attempts_hour = if_not_exists(attempts_hour, :zero) + :one,
      hour_window_started_at = if_not_exists(...),
      attempts_day = if_not_exists(...) + :one,
      ...
```

Three branches:

1. **First request ever** — row doesn't exist; `UpdateItem` with
   `attribute_not_exists(PK)` creates it.
2. **Within current windows** — increment counters; condition succeeds
   only if both counters are below cap.
3. **Window rolled** — counters reset, new `*_started_at`.

Real implementation needs two transactional steps for the rolling-window
case (read first, then conditional write with the read's `*_started_at`
in the condition) to avoid lost-update races. **Decision**: use a
two-call pattern (`GetItem` then conditional `UpdateItem`); the second
call's condition pins the `*_started_at` from the first read. Race-loser
retries once. Keeps the math simple at the cost of one extra DDB read
per call (cheap on-demand; this path runs at single-digit RPS at MVP).

`RateLimitExceeded.retry_after_seconds` is computed as
`min(hour_window_started_at + 3600 - now, day_window_started_at +
86400 - now)` — whichever boundary the caller is sitting against.

### `app/features/auth/errors.py`

```python
class AuthError(Exception):
    def __init__(self, code: str, http_status: int, message: str,
                 details: list[dict] | None = None,
                 retry_after: int | None = None) -> None: ...
```

Global FastAPI exception handler maps:

- `AuthError` → JSON envelope `{error: {code, message, details?, request_id}}`
  with the right `http_status` and optional `Retry-After` header.
- `RateLimitExceeded` → `AuthError("RATE_LIMITED", 429, ..., retry_after=…)`.
- `InvalidTokenError` / `UnauthenticatedError` → `AuthError("UNAUTHENTICATED",
  401, "Authentication required.")`.
- `pydantic.ValidationError` → `AuthError("VALIDATION_ERROR", 422,
  "Request body failed validation.", details=[{field, issue}, …])`.

The handler reads `request_id` from `request.state.request_id` (set by
the Phase 2b CoreMiddleware) so every error envelope carries it.

### `app/features/auth/models.py`

Eight request models + four response models. Highlights:

```python
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(min_length=1, max_length=128)
    currency: Literal["USD", "INR"]
    phone: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")

    model_config = {"extra": "forbid"}  # reject unknown keys
```

`extra: "forbid"` is mandatory across every request model so a typo'd
field becomes a 422, not a silently-ignored attacker payload.

### `app/features/auth/service.py`

Pure business logic — depends on `cognito_client`, `rate_limit`, DDB
table client (from `app.core.config`). Each public function takes
domain types in, returns domain types out, raises `AuthError` on
failure. Routes adapt HTTP ↔ domain.

### `app/features/auth/routes.py`

```python
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/signup", status_code=202)
@idempotent  # Powertools, only when Idempotency-Key header present
async def signup(req: SignupRequest) -> SignupResponse: ...

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest) -> VerifyEmailResponse: ...

@router.post("/resend-email-code", status_code=202)
async def resend_email_code(req: ResendEmailCodeRequest) -> ResendResponse: ...

@router.post("/login")
async def login(req: LoginRequest, response: Response) -> LoginResponse: ...
   # Sets cookie via response.set_cookie(...)

@router.post("/refresh")
async def refresh(request: Request, response: Response) -> RefreshResponse: ...

@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
) -> None: ...

@router.post("/forgot-password", status_code=202)
async def forgot_password(req: ForgotPasswordRequest) -> ForgotPasswordResponse: ...

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest) -> ResetPasswordResponse: ...
```

The router is mounted in `main.py` at `/v1` (so final paths are
`/v1/auth/...`).

## CDK Changes

### `apps/infra/stacks/api_stack.py`

**New constructor params**:

```python
def __init__(
    self,
    ...,
    user_pool: cognito.IUserPool,
    web_client: cognito.IUserPoolClient,
    ios_client: cognito.IUserPoolClient,
    android_client: cognito.IUserPoolClient,
    users_table: dynamodb.ITable,
    ...
):
```

**JWT authorizer** (using L2 alpha `aws_apigatewayv2_authorizers_alpha`
**or** the L1 `CfnAuthorizer` if alpha module is unavailable in the
pinned CDK):

```python
authorizer = apigwv2_authorizers.HttpJwtAuthorizer(
    "JwtAuthorizer",
    jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
    jwt_audience=[
        web_client.user_pool_client_id,
        ios_client.user_pool_client_id,
        android_client.user_pool_client_id,
    ],
    identity_source=["$request.header.Authorization"],
)
```

**Public auth-bootstrap routes** — explicit `add_routes` calls without
authorizer:

```python
PUBLIC_AUTH_ROUTES = [
    "/v1/auth/signup",
    "/v1/auth/verify-email",
    "/v1/auth/resend-email-code",
    "/v1/auth/login",
    "/v1/auth/refresh",
    "/v1/auth/forgot-password",
    "/v1/auth/reset-password",
]
for path in PUBLIC_AUTH_ROUTES:
    self.api_gateway.add_routes(
        path=path,
        methods=[apigwv2.HttpMethod.POST],
        integration=integration,
        # No authorizer => HTTP API treats it as auth=NONE.
    )
```

**Catch-all with JWT auth** — modify the existing `/{proxy+}` route to
attach the JWT authorizer. `/v1/health` remains a public **explicit**
route (more-specific routes win in HTTP API).

**Per-route throttling** — extend the CFN override on `default_stage` to
add `RouteSettings` for the three throttled routes:

```python
"RouteSettings": {
    "POST /v1/auth/login":              {"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10},
    "POST /v1/auth/resend-email-code":  {"ThrottlingRateLimit": 1, "ThrottlingBurstLimit": 5},
    "POST /v1/auth/forgot-password":    {"ThrottlingRateLimit": 1, "ThrottlingBurstLimit": 5},
}
```

**IAM grants**:

```python
self.lambda_function.add_to_role_policy(iam.PolicyStatement(
    actions=[
        "cognito-idp:SignUp",
        "cognito-idp:ConfirmSignUp",
        "cognito-idp:ResendConfirmationCode",
        "cognito-idp:InitiateAuth",
        "cognito-idp:GlobalSignOut",
        "cognito-idp:ForgotPassword",
        "cognito-idp:ConfirmForgotPassword",
        "cognito-idp:AdminGetUser",
    ],
    resources=[user_pool.user_pool_arn],
))
users_table.grant(self.lambda_function, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem")
```

(Using `users_table.grant(...)` instead of `grant_read_write_data` keeps
the action set tight — no `Scan`, no `BatchWriteItem`, no `DeleteItem`.)

### `apps/infra/app.py`

Pass the new params:

```python
api = ApiStack(
    ...,
    user_pool=auth.user_pool,
    web_client=auth.web_client,
    ios_client=auth.ios_client,
    android_client=auth.android_client,
    users_table=data.users_table,
)
api.add_dependency(auth)
api.add_dependency(data)
```

### `apps/infra/tests/test_synth.py`

Add assertions:

- `test_api_stack_jwt_authorizer_configured` — pool issuer URL +
  3-element audience list match.
- `test_api_stack_public_auth_routes_have_no_authorizer` — exact list
  matches the design.
- `test_api_stack_catch_all_route_uses_jwt_authorizer`.
- `test_api_stack_per_route_throttling` — login + resend + forgot rates.
- `test_api_stack_lambda_iam_cognito_actions_enumerated` — no `*`
  action; only the 8 listed; resource is the pool ARN.
- `test_api_stack_lambda_iam_ddb_actions_enumerated` — only Get/Put/Update.
- `test_api_stack_lambda_no_dynamodb_scan_or_delete` — explicit deny check.

## Idempotency for Signup

Use `aws_lambda_powertools.utilities.idempotency` decorator:

```python
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer, IdempotencyConfig, idempotent_function,
)

persistence = DynamoDBPersistenceLayer(table_name=config.users_table_name)
idempotency_config = IdempotencyConfig(
    event_key_jmespath='headers."idempotency-key"',
    payload_validation_jmespath="body",
    expires_after_seconds=86400,
    raise_on_no_idempotency_key=False,
)
```

Idempotency rows live in the **same Users table** as identity rows
(unlike Design 8 which puts them in the Transactions table — at MVP we
have only one table beyond Auth, and Design 7 explicitly allows
`AUTH_RATE#…` and `IDEMPOTENCY#…` rows in the Users table for now).

PK shape: `IDEMPOTENCY#<email_hash>#<key>`, SK = `META`. TTL via the
existing `ttl` attribute already configured on the table.

Powertools' decorator handles `idempotency-key`-mismatch (different
body, same key) → 422 `IDEMPOTENCY_KEY_MISMATCH`.

## Trade-offs

### Trade-off 1 — USER_PASSWORD_AUTH vs SRP for login

| Option | Pros | Cons |
|---|---|---|
| **USER_PASSWORD_AUTH (chosen)** | Simple JSON in/out; works without Amplify on the client; backend can rate-limit and inspect failures. | Password traverses our Lambda. TLS in transit + rate-limit + WAF mitigates. |
| USER_SRP_AUTH | Password never leaves client. | Requires Amplify or a Python SRP impl on the backend; Phase 2d will switch to Amplify-on-client which sidesteps this. |

**Decision**: USER_PASSWORD_AUTH at MVP. Phase 2d swaps the client to
Amplify SRP, the server keeps `USER_PASSWORD_AUTH` as a non-default
fallback (or removes it entirely after the client cuts over).

### Trade-off 2 — JWT verifier in Lambda even though API GW already verifies

| Option | Pros | Cons |
|---|---|---|
| **Both layers (chosen)** | Defense in depth; Lambda gets clean `Principal` from validated claims; works in test without API Gateway. | One extra JWKs fetch per cold start; ~5ms verification on hot path. |
| API GW only | Saves Lambda CPU. | Lambda has to parse claims from `event.requestContext.authorizer.jwt.claims` via the LWA-forwarded header — and LWA does not forward that. We'd need raw header re-parse anyway. |

**Decision**: both layers. The Lambda verification is also what makes
local pytest work without an API GW mock.

### Trade-off 3 — Refresh-token cookie path

| Option | Pros | Cons |
|---|---|---|
| `Path=/v1/auth` (chosen) | Cookie auto-attaches only to auth endpoints; never sent on other API calls. | Slightly less convenient for future "elevate session" prompts that aren't under /v1/auth. |
| `Path=/` | Cookie auto-attaches everywhere. | Bigger blast radius if a non-auth endpoint ever XSS leaks. |

**Decision**: `Path=/v1/auth` — minimum necessary surface.

### Trade-off 4 — Idempotency table location

| Option | Pros | Cons |
|---|---|---|
| **Reuse Users table (chosen)** | One IAM grant; one table to monitor. | Slight coupling of unrelated rows. |
| New IDEMPOTENCY table | Clean isolation; per-row TTL tuning. | Extra table = extra cost; extra IAM. |

**Decision**: Users table at MVP. If the Idempotency row count ever
becomes large enough to skew DDB metrics, split.

## Open Questions

- **Q1** — Should we move `idempotency-key` mismatch from 422 to 409?
  Powertools defaults to a custom `IdempotencyValidationError` (422 in
  practice). 422 is fine; document and move on.
- **Q2** — For login, should we expose `mfa_required` in the response
  shape now to forward-compat MFA? **Decision**: no, keep the response
  flat at MVP; MFA is post-MVP per Design 4.

## Summary

- Eight endpoints, six explicit-public + one explicit-authenticated +
  catch-all-authenticated.
- Two new core modules (`security.py`, `dependencies.py`); one new
  feature module (`auth/`).
- API Gateway HTTP API gains a JWT authorizer; CDK adds per-route
  throttling and least-privilege IAM grants.
- DDB-backed OTP rate-limiter (5/h, 20/day) shared between
  resend-email-code and forgot-password.
- HttpOnly Secure SameSite=Strict refresh-token cookie scoped to
  `/v1/auth`.
- Powertools idempotency on signup, backed by the Users table.
- Coverage 99%; 33 negative-test scenarios enumerated in
  requirements.md.
