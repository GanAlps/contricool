# Runbook — SMS spend alarm fires

**Alarm**: `contricool-prod-sms-spend` (when SNS MTD spend > $4 —
80% of the $5 monthly cap).

## Context

Phase 1 set the SNS account-level monthly spend cap at **$5** and
the AWS Budget at $20 warn / $30 critical. Hitting $4 in SMS
spend is either:

1. **Real signup volume** that's exceeding our 2,000-account
   monthly capacity (~$2.50 of SMS at India rates).
2. **SMS pumping attack** — an attacker spinning up signups to a
   premium-rate number to extract revenue from the SNS-to-SMS
   payout chain.

## 1. Identify

1. CloudWatch → Metrics → SNS → `SMSMonthToDateSpentUSD`. Plot the
   last 7 days.
2. CloudWatch Logs → `/aws/lambda/contricool-api-prod` →
   filter on `"event": "auth_signup"` for the day(s) with the
   spike. Group by `email_hash` (you'll see hashed emails, not the
   raw addresses — the redactor does its job).
3. Check if a single phone-prefix dominates (Cognito stores phone
   metadata on each signup; query CloudTrail for `SignUp` events
   if you need raw phone numbers, but **do NOT** save those to a
   shared channel).

## 2. Mitigate

- **Real volume**: file an SNS Service Quotas request to raise the
  monthly cap. Capture the increase in CDK in
  `apps/infra/stacks/shared_stack.py` so it redeploys with the
  stack.
- **Pumping attack**:
  - Set the SNS spend cap to $0 immediately (block all SMS — this
    will break new signups, but a bricked auth path is better than
    a $1,000 bill at 4 AM):
    `aws sns set-sms-attributes --attributes MonthlySpendLimit=0`
  - Add a feature flag in CDK to disable SMS-OTP entirely; route
    new users through email-only verification.
  - File a runbook entry for the attack window so the next
    quarterly review can decide whether to add WAF rate-limiting
    on `/v1/auth/signup`.

## 3. After-action

- The SMS cap reset on the 1st of next month is automatic. If you
  set it to $0, **remember to put it back** before users notice.
- Update `CLAUDE.md` Section 8 if the cap changes.
