# `friends` feature

The friends feature lets an authenticated user add another user by
email, list their friendships, remove a friendship, and read a balance
between themselves and a friend.

## Endpoints

All four are under `/v1/friends/*`, JWT-authenticated, behind the
API Gateway HTTP API authorizer.

### `POST /v1/friends/add`

Add a friend by email.

```http
POST /v1/friends/add
Authorization: Bearer <id_token>
Content-Type: application/json

{ "email": "alice@example.com" }
```

Success → 200:

```json
{
  "user_id": "01J...",
  "name": "Alice",
  "currency": "USD",
  "since": "2026-04-29T20:01:45Z"
}
```

Errors:

| Status | Code | Reason |
|---|---|---|
| 401 | `UNAUTHENTICATED` | Missing / invalid JWT |
| 404 | `USER_NOT_FOUND` | No registered user with that email |
| 409 | `CONFLICT` | Friendship already exists |
| 422 | `VALIDATION_ERROR` | Malformed body or non-email identifier |
| 422 | `SELF_ADD_FORBIDDEN` | You can't add yourself |
| 429 | `RATE_LIMITED` | 30 add-attempts/hour cap hit |

### `GET /v1/friends`

List the caller's friends, paginated by an opaque cursor.

```http
GET /v1/friends?limit=50&cursor=<opaque>
```

Success → 200:

```json
{
  "items": [
    {
      "user_id": "...",
      "name": "...",
      "currency": "USD",
      "since": "...",
      "balance": { "net": "0.00", "settlement_status": "settled" }
    }
  ],
  "next_cursor": "<opaque>" | null
}
```

`limit` is bounded `[1, 100]`, default 50. `next_cursor` is `null`
when the list is exhausted. The cursor is HMAC-signed and bound to
the requester's user_id at issue time — a cursor minted for User A
presented by User B → 422 `INVALID_CURSOR`.

Each item carries a `balance` summary: the requester-perspective net
balance with that friend (`net > 0` → friend owes you, `< 0` → you
owe). The list endpoint computes balances in a single pass over the
requester's transactions, so this is one round-trip rather than `N`
balance queries.

### `DELETE /v1/friends/{user_id}`

Hard-delete the canonical-pair friendship. Idempotent re-call returns
`404 USER_NOT_FOUND`. **Refuses with `409 BALANCE_NOT_SETTLED`** when
the requester still has a non-zero balance with the friend — the user
must settle up before removing them.

### `GET /v1/friends/{user_id}/balance`

Per-friend balance.

Success → 200:

```json
{
  "user_id": "01J...",
  "currency": "USD",
  "net": "0.00",
  "settlement_status": "settled",
  "last_transaction_at": null
}
```

Phase 3a returns zeros / `null`; Phase 4 fills in real numbers from
the transactions table. The shape is forward-compatible so the client
UI doesn't need to change.

## Configuration

| Env var / SSM | Source | Used for |
|---|---|---|
| `/contricool/<env>/ddb/users-table-name` | SSM (Phase 2b config) | Friendship rows + META + rate-limit |
| `/contricool/<env>/pii-salt` | SSM (Phase 2c) | Email lookup hash + cursor signing |

No new SSM parameters; no new IAM grants beyond the existing Users
table grant + the additions in `apps/infra/stacks/api_stack.py`
(Phase 3a adds `Query`, `BatchGetItem`, `DeleteItem`,
`TransactWriteItems`).

## Privacy invariants

1. **Friend lists are private.** Only `GET /v1/friends` exists; no
   endpoint exposes another user's friends list.
2. **Cross-user `DELETE` / `balance` mask as 404.** Asking about a
   friendship between two other users returns the same `404
   USER_NOT_FOUND` whether the friendship exists or not.
3. **Email-existence enumeration via `/add` is rate-limited up
   front.** The rate-limit increment runs *before* the GSI1 lookup,
   so failed attempts (404, 409, 422 self-add) all consume the
   bucket. A bad actor with no account info can't use `/add` as a
   "does this email exist?" oracle.
4. **No raw email or phone in any response.** The friend's
   `display_name` and `currency` are the only identity-touching
   fields exposed.
5. **No raw email in logs.** Logging emits only `requester_id` and
   `friend_id` (ULIDs) plus the event name.

## Rate limit

`POST /v1/friends/add` is rate-limited to 30 requests per rolling
hour per requester. Counter row: `PK=RATE#FRIEND_ADD#<requester_id>`,
`SK=COUNTER`, with a 24h TTL for cleanup. The route also carries an
API Gateway per-route throttle of 1 RPS / 5 burst.

## Friendship row schema

```
PK     = USER#<min(a,b)>
SK     = FRIEND#<max(a,b)>
GSI1PK = USER#<max(a,b)>
GSI1SK = FRIEND#<min(a,b)>
created_by, created_at
```

The polymorphic GSI1 lets a single user query reach friends on both
sides of the canonical pair without scanning. The list-friends
service merges the two sides in the Lambda — both queries return
sorted by user_id ascending, so a merge-sort is O(limit + lookahead).

## Cursor format

```
base64url( "<requester_id>:<last_friend_id>" "." hex(hmac_sha256(payload, pii_salt)) )
```

Tampering or cross-user reuse fails the HMAC check → 422
`INVALID_CURSOR`. Cursors aren't time-bound at MVP.

## Future work

- Phase 4 wires real balance numbers from the Transactions table.
- Phase 6 adds the per-friend mutation observability (CloudWatch
  alarms on add/remove rate, log-derived metrics).
- Pending friend requests, accept/decline, blocks, and not-on-platform
  invites are deferred per Design 6.
