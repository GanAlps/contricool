# Runbook — DynamoDB throttle alarm fires

**Alarm**: `contricool-<env>-ddb-throttle-{users,transactions}`.

## Why this is rare

Both tables are PAY_PER_REQUEST (on-demand). Throttling on
on-demand happens only when you exceed the per-second per-partition
ceiling (~3,000 RCU / 1,000 WCU per partition for hot keys), and
that's almost always a hot-partition design issue, not a capacity
issue.

## 1. Identify the hot key

1. CloudWatch → Metrics → DynamoDB → `ThrottledRequests` filtered
   by table name. Note the timestamps.
2. Logs Insights → `top-4xx-codes` saved query. Filter to the same
   timestamp range. Look for repeated `request_id` patterns or a
   single path being hit thousands of times.
3. If a single user_id dominates the access pattern, that's the
   hot partition (e.g. an attacker scraping their own friend list
   in a tight loop).

## 2. Mitigate

- **Friendly hot user** (e.g. an integration that's polling): get
  in touch + ask them to back off.
- **Abusive hot user**: enable WAF rate-based rule (manual until
  Phase 7 lands the WAF construct).
- **Genuinely hot partition** (e.g. a celebrity user with 50k
  friends): redesign the access pattern — do NOT raise capacity
  blindly because PAY_PER_REQUEST scales the table, not the
  partition.

## 3. After-action

- Capture the partition-key + access-pattern in a Linear issue.
- If a redesign is needed, create a `specs/<feature>/` design doc
  before any code change.
