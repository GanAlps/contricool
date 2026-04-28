# ContriCool — API Design

## Overview

This design defines the contract between ContriCool's web client (today) + mobile clients (future) and the backend. Design level: **HLD + LLD** (full endpoint inventory and shapes are needed because Design 7 already locks the data model). Headlines: **REST + JSON over HTTPS**, **path-based versioning at `/v1`**, **Pydantic-emitted OpenAPI 3.1** as the single source of truth, **standard error envelope** with stable `code`s, **cursor pagination**, **client-supplied `Idempotency-Key` header** on writes that side-effect (transactions/auth), **rate-limited per-user** at the API Gateway layer.

## Style decision: REST vs GraphQL

| Option | Pros | Cons |
|---|---|---|
| **REST + JSON (chosen)** | FastAPI emits OpenAPI for free; cheap on API Gateway HTTP API ($1/M); plays well with HTTP caching/WAF; trivial for mobile clients to consume; easy to debug with curl. | Multiple round-trips for nested data; over/under-fetching. |
| GraphQL via AppSync | One round-trip; tailored client queries; subscriptions ready. | AppSync query pricing higher per call; more learning curve; less obvious caching; resolvers need separate code; loses Pydantic-as-source-of-truth. |
| gRPC | Binary efficiency. | Browser support requires gRPC-Web proxy; not first-class on API Gateway HTTP API. |

**Decision: REST + JSON.** Aligns with FastAPI, keeps cost minimal, and the "chunky" CRUD shape of ContriCool doesn't benefit much from GraphQL.

## Conventions

### Versioning

- **Path-based**: `/v1/...`. Future breaking changes go to `/v2/...` and run side-by-side until clients migrate.
- **Header `X-API-Version: 1`** echoed in responses for telemetry.
- We treat `/v1` as **stable**. Additive changes (new fields, new endpoints) are fine; field removals or shape changes require `/v2`.

### URL & method conventions

- Lowercase, hyphenated paths (`/v1/transactions`, not `/v1/Transactions`).
- Resources are plural (`/transactions`); singular only for singletons (`/me`).
- Standard methods: `GET` (read), `POST` (create / non-idempotent action), `PUT` (full replace, idempotent), `PATCH` (partial), `DELETE`.
- Action endpoints when CRUD doesn't fit: `POST /v1/friends/{id}:accept` (Google AIP-style colon action).

### Content type

- All requests and responses: `application/json; charset=utf-8`.
- Decimal monetary amounts are **strings** in JSON to avoid float drift (`"amount": "12.50"`); Pydantic coerces to/from `Decimal`.
- Dates: ISO-8601 (`"2026-04-27"` for date, `"2026-04-27T10:30:00Z"` for timestamps, always UTC).
- Phone numbers: E.164 strings (`"+15551234567"`).

### Error envelope

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Sum of percents must be 100.",
    "details": [
      {"field": "members[2].percent", "issue": "value out of range"}
    ],
    "request_id": "01J..."
  }
}
```

Stable `code` set:

| HTTP | code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Body/query/path failed schema validation |
| 401 | `UNAUTHENTICATED` | Missing/invalid/expired token |
| 403 | `FORBIDDEN` | Authenticated but not allowed |
| 404 | `NOT_FOUND` | Resource not found (or hidden via not-found mask) |
| 409 | `CONFLICT` | Resource state conflict (stale edit, duplicate signup) |
| 412 | `PRECONDITION_FAILED` | `If-Match` header mismatch |
| 422 | `UNPROCESSABLE` | Semantic validation (currency mismatch, non-friend member) |
| 429 | `RATE_LIMITED` | Throttled |
| 500 | `INTERNAL` | Server bug |
| 503 | `UNAVAILABLE` | DDB/Cognito throttled or transient outage |

### Pagination

All list endpoints use **opaque cursor pagination**:

```
GET /v1/transactions?limit=20&cursor=<opaque>
```

Response:
```json
{
  "items": [...],
  "next_cursor": "<opaque>",
  "has_more": true
}
```

`limit` defaults to 20, max 100. Cursor encodes the LastEvaluatedKey from DDB (base64 of JSON), encrypted-and-MAC'd with the project KMS so clients can't tamper. Server validates MAC.

### Rate limiting

- **API Gateway HTTP API per-route throttling**: default account 10k RPS; specific bursty routes capped:
  - `POST /v1/auth/login` — burst 10, sustained 5/s.
  - `POST /v1/auth/resend-*-code` — burst 5, sustained 1/s.
  - `POST /v1/friends/request` — burst 10, sustained 5/s.
- **App-level per-user rate-limits** for OTP and friend requests via DDB rate-limit rows (see Design 4 + 7).

### Idempotency

`POST` and `DELETE` endpoints that mutate accept an optional `Idempotency-Key` header (UUIDv4). If present, the server stores `(user_id, key, response)` for 24h in DDB and returns the cached response on retry. Implemented via `aws-lambda-powertools.idempotency` decorator backed by the **`ContriCool-Transactions-<env>`** table (kept with the financial-ledger writes since most idempotent ops are transaction-create / transaction-restore):

| Item | Table | PK | SK | TTL |
|---|---|---|---|---|
| Idempotency record | `ContriCool-Transactions-<env>` | `IDEMPOTENCY#<user_id>#<key>` | `META` | 24h |

Required for: `POST /v1/auth/signup`, `POST /v1/transactions`, `POST /v1/transactions/{id}:restore`. Optional everywhere else.

### Concurrency control

- `GET` responses include `ETag: <updated_at>`.
- Clients may send `If-Match: <updated_at>` on `PATCH`/`PUT`/`DELETE`. Server uses DDB `ConditionExpression` to enforce; mismatch → 412.

### Authentication / Authorization

- All `/v1/*` routes require `Authorization: Bearer <jwt>` **except** the explicitly-public auth bootstrap routes listed below.
- Refresh-token cookie (`HttpOnly`, `Secure`, `SameSite=Strict`, scoped to `.contricool.com`) on `/v1/auth/refresh` only.
- AuthZ enforced per Design 5.

### Request ID

- API Gateway sets `X-Amz-Request-Id`; Lambda generates an internal `request_id` (ULID) used in logs.
- Both echoed in response headers and in error envelopes (`error.request_id`).

### CORS

At MVP, web and API are **same-origin** (single CloudFront distribution per env, path-based routing — Designs 1 & 9). Same-origin means CORS is effectively a no-op for the web client. We still configure API Gateway CORS defensively:

- Allowed origins: the env's CloudFront default domain (e.g. `https://d-prod.cloudfront.net`); when `contricool.com` lands, we add it as an allowed origin without app changes.
- Allowed methods: `GET, POST, PUT, PATCH, DELETE, OPTIONS`.
- Allowed headers: `authorization, content-type, idempotency-key, if-match, x-api-version`.
- Credentials: `true` (web's refresh-token cookie attaches automatically since it's same-origin; the flag is set for completeness and for any future cross-origin scenarios).
- Native iOS/Android clients don't enforce CORS (browser-only) but use the same allowlist on the server side.

## Endpoint inventory

Public routes are marked `🔓`; all others require JWT.

### Health

| Method | Path | Purpose |
|---|---|---|
| GET 🔓 | /v1/health | liveness, returns `{status: "ok", version, commit}` |

### Auth

| Method | Path | Purpose |
|---|---|---|
| POST 🔓 | /v1/auth/signup | Start signup |
| POST 🔓 | /v1/auth/verify-email | Confirm email — activates account |
| POST 🔓 | /v1/auth/resend-email-code | Resend (rate-limited) |
| POST 🔓 | /v1/auth/login | SRP login → tokens + refresh cookie |
| POST 🔓 | /v1/auth/refresh | Refresh tokens via cookie |
| POST | /v1/auth/logout | Revoke refresh token + clear cookie |
| POST 🔓 | /v1/auth/forgot-password | Send reset code |
| POST 🔓 | /v1/auth/reset-password | Confirm reset with code |

Sample shapes:

`POST /v1/auth/signup`
```json
{
  "email": "alice@example.com",
  "password": "...",
  "name": "Alice",
  "currency": "USD",
  "phone": "+15551234567"   // optional; stored unverified in Cognito; not used for any search/auth
}
```
Response 202:
```json
{ "user_id": "01J...", "status": "PENDING_VERIFICATION" }
```

The only verification step is the email code; account becomes active on `POST /v1/auth/verify-email`. Phone (if provided) is stored as an unverified Cognito attribute and the UI displays it with an "(unverified)" tag.

`POST /v1/auth/login`
```json
{ "email": "alice@example.com", "password": "..." }
```
Response 200 (sets `Set-Cookie: rt=...`):
```json
{ "access_token": "...", "id_token": "...", "expires_in": 3600, "user": { "user_id": "...", "name": "Alice", "currency": "USD" } }
```

The `user` object is built from a `GetItem` on `ContriCool-Users-<env>` `USER#<user_id>#META` after Cognito issues tokens. `currency` (and any future preference) lives only in DDB, never in Cognito attributes — see Design 4 for the rationale. The same shape is returned by `GET /v1/me`.

### Profile (`/me`)

| Method | Path | Purpose |
|---|---|---|
| GET | /v1/me | Get my profile |
| PATCH | /v1/me | Update display_name (currency immutable at MVP) |
| DELETE | /v1/me | Soft-delete account (see Design 13) |

### Friends

At MVP friendship is undirected and binary — no accept/decline, no blocking, no invites for non-users (Design 6). The endpoint surface is correspondingly small.

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/friends/add | Add a friend by exact email (auto-bilateral when target exists) |
| GET | /v1/friends | List my friends |
| DELETE | /v1/friends/{user_id} | Remove friendship (drops the canonical row from both sides) |
| GET | /v1/friends/{user_id}/balance | Net balance with this friend |

`POST /v1/friends/add` (idempotency-key optional)
```json
{ "identifier": "bob@example.com" }
```
The `identifier` field accepts an **email only** at MVP. Phone is not a friend-add key (see Design 4 / CONSTRAINTS.md).

Response 200 (target exists):
```json
{ "friend": { "user_id": "01J_bob", "display_name": "Bob" } }
```
Response 400 (identifier not parseable as email):
```json
{ "error": { "code": "INVALID_IDENTIFIER", "message": "Friend lookup requires a valid email address.", "request_id": "01J..." } }
```
Response 404 (target not on platform):
```json
{ "error": { "code": "USER_NOT_FOUND", "message": "No ContriCool user with this email.", "request_id": "01J..." } }
```
Response 409 (already friends):
```json
{ "error": { "code": "CONFLICT", "message": "You are already friends with this user.", "request_id": "01J..." } }
```

The 404 response is honest about target existence — accepted MVP trade-off (Design 5/6) since the only way to probe is by knowing the exact email (no enumeration affordances anywhere).

`GET /v1/friends?cursor=...`
```json
{
  "items": [
    { "user_id": "01J_bob", "display_name": "Bob", "since": "2026-04-15" }
  ],
  "next_cursor": null, "has_more": false
}
```

`DELETE /v1/friends/{user_id}` — either party. Returns 204. Existing transactions remain readable; new transactions blocked until re-added.

`GET /v1/friends/{user_id}/balance`
```json
{
  "friend_user_id": "01J_bob",
  "currency": "USD",
  "net": "12.50",         // positive = friend owes me; negative = I owe friend
  "as_of": "2026-04-27T10:30:00Z"
}
```

### Transactions

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/transactions | Create |
| GET | /v1/transactions | List my transactions; filters: `friend_id`, `from`, `to`, `type`, `include_deleted` |
| GET | /v1/transactions/{txn_id} | Get one |
| PUT | /v1/transactions/{txn_id} | Replace (creator-only, with `If-Match`) |
| DELETE | /v1/transactions/{txn_id} | Soft-delete (creator-only) |
| POST | /v1/transactions/{txn_id}:restore | Restore within 30d |

`POST /v1/transactions` (idempotency-key required)
```json
{
  "name": "Dinner at Joe's",
  "type": "expense",
  "amount": "60.00",
  "currency": "USD",
  "txn_date": "2026-04-26",
  "split_method": "equal",
  "members": [
    { "user_id": "01J_alice" },
    { "user_id": "01J_bob" },
    { "user_id": "01J_carol" }
  ],
  "payers": [
    { "user_id": "01J_alice", "paid_amount": "60.00" }
  ],
  "note": "Saturday night"
}
```

Response 201:
```json
{
  "txn_id": "01J...",
  "creator_id": "01J_alice",
  "name": "Dinner at Joe's",
  "type": "expense",
  "amount": "60.00",
  "currency": "USD",
  "txn_date": "2026-04-26",
  "split_method": "equal",
  "members": [
    { "user_id": "01J_alice", "owed_amount": "20.00" },
    { "user_id": "01J_bob",   "owed_amount": "20.00" },
    { "user_id": "01J_carol", "owed_amount": "20.00" }
  ],
  "payers": [
    { "user_id": "01J_alice", "paid_amount": "60.00" }
  ],
  "note": "Saturday night",
  "created_at": "2026-04-26T19:32:11Z",
  "updated_at": "2026-04-26T19:32:11Z",
  "deleted_at": null
}
```

`GET /v1/transactions?friend_id=01J_bob&limit=20&cursor=...` returns paged transactions in which both me and Bob are members, newest first.

`PUT /v1/transactions/{id}` requires `If-Match: <updated_at>`. Body is the full transaction (members, payers, etc.), server re-validates and re-derives `owed_amount`.

`POST /v1/transactions/{id}:restore` valid within 30 days of deletion; idempotency-key required.

### Admin (post-MVP, not in v1 surface)

Reserved namespace `/v1/admin/*` exists in the OpenAPI but contains no endpoints at MVP; reserved so future additions don't bump version.

## OpenAPI authoring & codegen

- FastAPI emits `/openapi.json` automatically from Pydantic models + route decorators.
- A pre-commit hook + CI step exports it to `packages/openapi/openapi.yaml`.
- `openapi-typescript` regenerates `packages/client-ts/src/schema.d.ts`.
- Web client uses `openapi-fetch` to make calls with end-to-end types.

CI gate: if a PR changes Pydantic models or routes but `openapi.yaml` and `schema.d.ts` weren't regenerated, the build fails.

## Mobile compatibility considerations

- All authentication uses bearer tokens in headers (no cookies for mobile). The refresh-token cookie is web-specific; mobile uses the secure platform store (per Design 4) and calls Cognito's `InitiateAuth(REFRESH_TOKEN_AUTH)` directly via Amplify instead of `/v1/auth/refresh`.
- Idempotency-key is mandatory for create-transaction → mobile retries on flaky networks won't double-charge.
- Pagination + ETags reduce bandwidth on slow mobile networks.
- All endpoints are platform-agnostic; no `User-Agent` sniffing or device-specific responses.

## Security Considerations

- **No `Server` header leak** — strip `X-Powered-By`-style headers.
- **`Strict-Transport-Security` header** added at CloudFront (`max-age=31536000; includeSubDomains; preload`).
- **`Content-Security-Policy`** for the web app set at CloudFront; APIs return `nosniff` and a strict CSP for any HTML error pages.
- **CORS** locked to known origins; no `Access-Control-Allow-Origin: *`.
- **JSON-only** request body acceptance; reject `application/x-www-form-urlencoded` and `multipart/form-data` at MVP (no file uploads).
- **Body size limits**: API Gateway max 10 MB; FastAPI rejects bodies >100 KB at MVP — transactions are small.
- **Field-level redaction in logs** — `email`, `phone`, `password`, `code`, `otp`, `Authorization`, `Cookie` go through Powertools Logger denylist.
- **Replay protection on idempotency keys**: stored with `(user_id, key)` so cross-user replay is impossible.

## Open Questions

1. **Should admins fetch by email/phone?** Out of scope for `/v1`; admin tooling is separate and uses console + CDK ops at MVP.
2. **Webhooks?** None at MVP. If integrators ever want them, separate `/v1/webhooks/...` namespace; out of scope.
3. **API version sunset policy?** When `/v2` arrives, `/v1` runs ≥6 months in parallel. Re-decide at that time.

## Summary

- **REST + JSON** at `/v1`, OpenAPI 3.1 emitted by FastAPI as the single source of truth → typed TS SDK consumed by web today and mobile tomorrow.
- **Standard envelope** for errors with stable `code`s, **cursor pagination**, **ETag/If-Match** for optimistic concurrency, **`Idempotency-Key`** required on signup + transaction-create + restore.
- **Endpoint inventory** covers auth (8), profile (3), friends (4 incl. balance), transactions (6) — total ~23 endpoints in `/v1`.
- **Mobile-ready**: no web-only assumptions; refresh-token cookie isolated to one endpoint; bearer-token everywhere else.
- **Rate limiting at API Gateway** for auth and friend-request routes; idempotency table in DDB protects against retry storms.
