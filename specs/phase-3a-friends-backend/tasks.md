# Phase 3a — Friends Backend — Tasks

Six implementation phases. Each ends with the test suite green and
coverage ≥ 99% on everything written so far. Phases ship as a single
PR with one commit per phase.

---

## Phase 1 — Models + cursor

- [ ] **T1.1** Create `apps/api/app/features/friends/__init__.py`.
- [ ] **T1.2** Implement `apps/api/app/features/friends/models.py`
      per design.md §"Pydantic models".
- [ ] **T1.3** Implement `apps/api/app/features/friends/cursor.py`:
      `encode(requester_id, last_friend_id) -> str`,
      `decode(cursor, requester_id) -> str`,
      `class InvalidCursorError(Exception)`.
      HMAC-SHA-256 over `<requester_id>:<last_friend_id>` using the
      pii-salt from `app.core.lookup_hash`. Output is
      base64url(payload + "." + hmac_hex).
- [ ] **T1.4** Tests `apps/api/tests/features/friends/test_cursor.py`:
      - encode → decode round-trip.
      - decoding with wrong requester_id → InvalidCursorError.
      - tampered hmac → InvalidCursorError.
      - malformed base64 / missing dot → InvalidCursorError.
      - empty cursor → InvalidCursorError (don't accept "" as a
        sentinel).
- [ ] **T1.5** Tests `apps/api/tests/features/friends/test_models.py`:
      - `AddFriendRequest` rejects non-EmailStr (covers N2).
      - `AddFriendRequest` rejects extra fields (`extra=forbid`).
      - `ListFriendsQuery` clamps invalid `limit` (N11, N12).
- [ ] **T1.6** Run `pytest --cov=app tests/ --cov-fail-under=99` —
      green.

## Phase 2 — Repository (DDB)

- [ ] **T2.1** Implement `apps/api/app/features/friends/repository.py`:
      - `find_user_by_email(email) -> str | None` — GSI1 query on
        `EMAIL#<lookup_hash>`.
      - `get_user_meta(user_id) -> UserMeta | None` — base GetItem.
      - `batch_get_user_metas(user_ids: list[str]) -> dict[str, UserMeta]`.
      - `create_friendship(a_id, b_id, created_by) -> None` —
        `TransactWriteItems` with `attribute_not_exists(PK)` cond.
        Maps `ConditionalCheckFailedException` → `ConflictError`.
      - `delete_friendship(a_id, b_id) -> bool` — `DeleteItem` with
        `attribute_exists(PK)` cond; returns True on hit, False on
        miss.
      - `friendship_exists(a_id, b_id) -> bool` — base GetItem with
        ProjectionExpression.
      - `query_friend_ids_one_side(user_id, fetch_limit, last_friend_id)`
        runs the base + GSI1 queries, returns
        `(friends_with_since: list[tuple[str, datetime]], has_more: bool)`.
- [ ] **T2.2** Tests `apps/api/tests/features/friends/test_repository.py`
      against moto:
      - find_user_by_email — hit and miss.
      - get_user_meta — hit and miss.
      - batch_get_user_metas — empty input, partial hits.
      - create_friendship — happy + ConflictError on duplicate.
      - delete_friendship — hit returns True, miss returns False.
      - friendship_exists — both directions of canonical pair.
      - query_friend_ids_one_side — base-only / GSI1-only / both
        sides / pagination.
- [ ] **T2.3** Run coverage — green.

## Phase 3 — Rate-limit

- [ ] **T3.1** Implement `apps/api/app/features/friends/rate_limit.py`:
      - `class FriendAddRateLimitExceeded(Exception)` with
        `retry_after_seconds: int`.
      - `consume_friend_add(user_id) -> None` — conditional
        `UpdateItem` on `RATE#FRIEND_ADD#<user_id>` / `COUNTER`,
        atomic increment with hour-window roll, raises on cap (30/h).
        TTL = now + 24h.
      - One-retry race-loss path mirroring `auth/rate_limit.py`.
- [ ] **T3.2** Tests `apps/api/tests/features/friends/test_rate_limit.py`:
      - First call creates the row.
      - 30 calls in same hour all succeed; 31st raises with
        `retry_after_seconds <= 3600 and > 0`.
      - Window roll: timestamp manipulated so the conditional
        update path takes the "roll the window" branch and resets
        `attempts_hour` to 1.
      - Race-loss retry: mock `ConditionalCheckFailedException` on
        first attempt, succeed on second.
- [ ] **T3.3** Run coverage — green.

## Phase 4 — Service + `is_friend` policy helper

- [ ] **T4.1** Update `apps/api/app/core/policy.py`:
      - Add `is_friend(user_id, other_user_id, *, ddb=None) -> bool`.
        Signature accepts optional `ddb` for tests.
- [ ] **T4.2** Implement `apps/api/app/features/friends/errors.py`:
      Per-error classes (InvalidIdentifierError, UserNotFoundError,
      ConflictError, SelfAddForbiddenError, SelfActionForbiddenError,
      InvalidCursorError, RateLimitedError) extending the existing
      Phase 2c base class. Each carries `code`, `http_status`,
      `message`.
- [ ] **T4.3** Implement `apps/api/app/features/friends/service.py`:
      - `add_friend(requester_id, email)` per design.md §
        "Add-friend — the rate-limit-before-lookup invariant".
      - `list_friends(requester_id, limit, cursor)` per design.md §
        "List-friends merge-sort pagination".
      - `remove_friend(requester_id, target_id)` —
        `delete_friendship`; if False → UserNotFoundError.
      - `get_balance(requester_id, target_id)` — verify
        `friendship_exists`; if False → UserNotFoundError; else
        return zeroed `FriendBalanceResponse` reading the requester's
        currency from their META row.
- [ ] **T4.4** Tests `apps/api/tests/core/test_policy_is_friend.py`:
      - Returns False for self-pair (N6 covers via service).
      - Returns True iff the canonical-pair row exists.
      - Order-independent: both `is_friend(A, B)` and `is_friend(B, A)`.
- [ ] **T4.5** Tests `apps/api/tests/features/friends/test_service.py`:
      - Service-level happy paths for the four operations.
      - Service-level error paths exercising each per-error class.
- [ ] **T4.6** Run coverage — green.

## Phase 5 — Routes + integration tests + log redaction

- [ ] **T5.1** Implement `apps/api/app/features/friends/routes.py`:
      - `POST /add` → `service.add_friend`.
      - `GET /` → `service.list_friends` (query params via Pydantic
        `Depends`).
      - `DELETE /{user_id}` — validate ULID, then
        `service.remove_friend`.
      - `GET /{user_id}/balance` → `service.get_balance`.
      - All routes use `current_principal()` dependency.
- [ ] **T5.2** Update `apps/api/app/main.py`:
      - `api.include_router(friends_routes.router, prefix="/v1")`.
      - Wire the new error classes into the existing exception
        handler.
- [ ] **T5.3** Tests `apps/api/tests/features/friends/test_add.py`:
      - Happy path (200 + correct response shape).
      - N1 (phone-shaped → 400 INVALID_IDENTIFIER).
      - N2 (malformed email → 422).
      - N3 (empty body → 422).
      - N4 (no matching email → 404).
      - N5 (existing friend → 409).
      - N6 (self-add → 422 SELF_ADD_FORBIDDEN).
      - N9 (31st add in 1h → 429 + Retry-After).
- [ ] **T5.4** Tests `apps/api/tests/features/friends/test_list.py`:
      - Empty list (no friendships).
      - Single page (≤ limit).
      - Cursor walk: page through 30 friends with limit=10.
      - Mix of base-side + GSI1-side rows.
      - N11 / N12 (limit bounds).
      - N13 (tampered cursor → 422 INVALID_CURSOR).
      - N15 (no email/phone in any field of any item).
- [ ] **T5.5** Tests `apps/api/tests/features/friends/test_remove.py`:
      - Happy (204).
      - N17 (non-friend → 404).
      - N18 (self → 422).
      - N19 (malformed user_id → 422).
- [ ] **T5.6** Tests `apps/api/tests/features/friends/test_balance.py`:
      - Happy (200, all-zero shape).
      - N21 (non-friend → 404).
      - N22 (self → 422).
      - N23 (malformed user_id → 422).
- [ ] **T5.7** Tests
      `apps/api/tests/features/friends/test_cross_user_privacy.py`:
      - N25 (User C accesses friend balance for B who is A's friend
        → 404).
      - N26 (User C deletes friendship between A and B → 404).
      - N27 (no enumeration: USER_NOT_FOUND vs CONFLICT only).
      - N28 (concurrent-add: mock TransactWriteItems
        ConditionalCheckFailed on the second writer → 409 to one
        side, success to the other).
- [ ] **T5.8** Tests
      `apps/api/tests/features/friends/test_friends_security.py`:
      - N7 (no auth → 401, all 4 routes).
      - N8 (bad/expired/wrong-pool JWT → 401, all 4 routes; reuse
        Phase 2c jwt-helpers).
      - N10 (log redaction: spy on Powertools logger; assert no
        raw email in any log line during a successful and failed
        add).
      - N14 (cursor forgery: cursor minted for User A presented by
        User B → 422 INVALID_CURSOR).
      - N16 / N20 / N24 already covered above as 401 cases.
- [ ] **T5.9** Run coverage — `friends/**` ≥ 99%, project floor ≥ 99%.

## Phase 6 — CDK throttle + synth tests + OpenAPI + docs + final pass

- [ ] **T6.1** Update `apps/infra/stacks/api_stack.py` `_ROUTE_THROTTLES`
      adding the friends-add entry. Existing Stage→Route DependsOn
      machinery handles deploy ordering.
- [ ] **T6.2** Add synth tests in `apps/infra/tests/test_synth.py`:
      - N29: assert no `dynamodb:Scan` action in api_stack IAM policies.
      - N30: assert no resource statement uses `dynamodb:*`.
      - N31: assert `POST /v1/friends/add` is in the synthesised
        Stage's RouteSettings + has a corresponding throttled-route
        DependsOn.
- [ ] **T6.3** Run `cd apps/infra && pytest` — green.
- [ ] **T6.4** Regenerate the OpenAPI spec and SDK schema:
      ```bash
      make openapi
      ```
      Commit `packages/openapi/openapi.yaml` +
      `packages/client-sdk/src/schema.d.ts` updates.
- [ ] **T6.5** Verify drift: `make openapi-check` — clean.
- [ ] **T6.6** Write `apps/api/app/features/friends/README.md`:
      - What the feature does.
      - The 4 endpoints with request/response shapes.
      - Error envelope.
      - Rate-limit semantics.
      - Cursor format note.
      - Privacy notes (friend lists private; cross-user balance/remove
        masked as 404).
- [ ] **T6.7** Update root `README.md` mention of friends being live.
- [ ] **T6.8** Run final
      `pytest --cov=app tests/ --cov-fail-under=99` — green.
- [ ] **T6.9** `ruff check apps/api && mypy --strict apps/api/app` —
      clean.
- [ ] **T6.10** Commit per phase; push; open PR;
      address pr-code-reviewer findings; merge after green.

## Verification (manual, post-deploy)

After dev deploy:

1. Sign up two test users (`a@example.com`, `b@example.com`).
2. As A, `POST /v1/friends/add { "email": "b@example.com" }` → 200.
3. As A, `GET /v1/friends` → A's list contains B.
4. As B, `GET /v1/friends` → B's list contains A.
5. As A, repeat the add → 409 CONFLICT.
6. As A, `DELETE /v1/friends/{B_id}` → 204.
7. As A, `GET /v1/friends` → empty.
8. As A, 31 rapid `/add` calls → 31st returns 429.
9. CloudWatch Logs: confirm no log line contains `b@example.com`.

If all nine pass, Phase 3a's checkpoint is met.
