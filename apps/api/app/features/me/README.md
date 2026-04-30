# `me` feature

Endpoints that act on the requesting user's own account.

| Method | Path | Purpose |
|---|---|---|
| `DELETE` | `/v1/me` | Soft-deactivate the requester. Sets `status=deactivated` + `deactivated_at` on the Users META row, then `AdminDisableUser` + `AdminUserGlobalSignOut` in Cognito. Idempotent — a second call on an already-deactivated user is a no-op (still 204). |
| `PATCH` | `/v1/me/profile` | Update the requester's display name. Body: `{name: str}`. Email and currency are intentionally not editable from this surface; any extra body field is rejected with 422 `VALIDATION_ERROR`. |
| `GET` | `/v1/me/export` | Returns a JSON dump of the requester's profile, friendships, and every transaction they are a member of. Rate-limited to 1 export per 24 hours via a DDB sliding-window counter (returns 429 with `retry_after_seconds` on violation). |

## Account-deletion lifecycle

1. **Soft-deactivate (this feature).** The Users META row records `status=deactivated`,
   `deactivated_at`, and `email_for_cleanup`. Cognito disables the user and global-signs-out
   every active session.
2. **30-day grace.** During this window the user is unreachable but their data is
   physically intact, so support could in principle restore the account on request.
3. **Hard-delete (cleanup Lambda — `app/cleanup/accounts.py`).** Friendship rows are
   deleted, the Users META row is hard-deleted, and `AdminDeleteUser` is called in
   Cognito so the email can be re-registered. Transaction MEMBER rows are *not*
   anonymised — they only carry an opaque ULID, never PII, so surviving members of a
   shared transaction continue to see the transaction with the deleted user shown as
   "—" (since `friends_repo.get_user_meta` returns `None` for the missing user).

## Configuration

- `EXPORT_COOLDOWN_SECONDS` — server-side cooldown between exports (24 h).
- `ACCOUNT_RETENTION_DAYS` — grace window before the cleanup pass hard-deletes
  the user. Lives in `app/cleanup/accounts.py`.
- Cognito user pool ID is read from `config.load().cognito_user_pool_id`.

## Notable rate limits

The export quota is enforced through a `last_at`-style row in the Users table
(`PK=USER#<id>`, `SK=EXPORT_QUOTA`) using a DDB ConditionExpression sliding window —
the same pattern Phase 2c uses for OTP rate-limits.
