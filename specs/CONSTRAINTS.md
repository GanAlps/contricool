# ContriCool — Cross-Cutting Constraints

These are the foundational decisions that shape every design. Locked on 2026-04-27 before any design work began. Each design should re-read this and call out where it leans on these constraints.

## 1. Scale (v1)

- **Launch**: < 100 DAU
- **Month 12**: < 1,000 DAU

Implication: hobbyist scale. Pure serverless that auto-scales-to-zero is the right default. Don't over-engineer for traffic that isn't there.

## 2. Geographic Scope

- **Markets**: US + India (both at launch)

Implications:
- Single AWS region with global edge — likely **us-east-1** + CloudFront (lowest latency to US, acceptable to India via CloudFront edge POPs). Re-validate in Hosting Design.
- Compliance: CCPA-leaning for US + India's DPDP Act for India. No GDPR unless EU users sneak in (treat as guard-rail, not target).
- SMS delivery: SNS / Pinpoint must support both +1 (US) and +91 (India) numbers. Cost is non-trivial in India — design verification flow accordingly.

## 3. Currency

- **v1**: Single currency per user. Each user picks their default currency at signup (e.g. USD, INR).
- **Out of scope for v1**: cross-currency transactions, FX conversion, mixed-currency balances.
- **Future**: multi-currency per transaction with per-friend balance ledgers.

Implications:
- Schema must store `currency` on the user (and probably on each transaction) from day one to avoid migration when multi-currency lands.
- Within v1, all transactions for a given user will share the user's chosen currency — UI enforces this.
- Friends with different default currencies is a v1 corner case — Domain Design must specify (likely: friendship works across currencies, but each transaction is in one currency, and balances stay separated).

## 4. Account Model

- **Email AND phone both required** at signup.
- **Both verified** before the account is active (email link + SMS OTP).

Implications:
- Two verification flows must complete before first login. Higher friction; UX must make this smooth (can run in parallel).
- Friend lookup works by either email or phone (per requirement #2).
- Cognito User Pools is a strong fit — supports both as standard attributes with verification.

## 5. Budget

- **Target**: $0–$30 / month for the first 12 months. Stay in AWS Free Tier as long as possible.

Implications & constraints on every design:
- **Compute**: Lambda only (free tier: 1M requests/mo + 400k GB-sec). Avoid always-on services (no EC2, no Fargate-on-demand idle).
- **Data**: DynamoDB on-demand (free tier: 25 GB storage + 25 RCU/WCU). No Aurora Serverless v2 (no free tier, ~$50/mo minimum).
- **Frontend**: S3 + CloudFront (free tier: 1 TB/mo CloudFront egress for 12 months, then expensive — re-evaluate post-year-1).
- **Auth**: Cognito (free tier: 50k MAU).
- **Email**: SES (free tier: 62k/mo from Lambda).
- **SMS**: SNS — **not free**. ~$0.0075/SMS in US, ~$0.02–$0.05 in India. With <1k DAU and OTP-on-signup-only, expect <$5/mo.
- **Observability**: CloudWatch free tier covers basics. Defer X-Ray, RUM, Synthetics until post-launch.
- **WAF**: ~$5/mo + $1/rule + traffic. Probably skip at MVP, add when abuse appears. Use API Gateway throttling for now.
- **Secrets**: SSM Parameter Store (free standard tier) over Secrets Manager ($0.40/secret/mo).
- **No NAT Gateway** ($32/mo each). No VPC at all if Lambda doesn't need one — keep functions out of VPC.
- **No multi-region**. Single region only.

## 6. Timeline

- **v1 launch target**: 1–3 months from start.

Implications:
- Design phase budget: ~2 weeks for all 14 designs (one or two per day, reviewed in batches per the plan).
- Implementation budget: ~6–10 weeks.
- Defer post-launch: advanced dashboards, multi-region, push notifications, social federation, mobile apps.

## 7. Team

- **Solo developer.**

Implications:
- CI/CD: GitHub Actions over CodePipeline (lower setup cost, no extra AWS spend).
- Repo: monorepo by default (single PR for full-stack changes).
- Reviews: self-review + automated checks (lint, type-check, tests, coverage).
- IaC: AWS CDK in Python (matches backend language, single-language stack).
- On-call: just CloudWatch Alarms → SNS → email. No PagerDuty.
- Operational docs lean on AWS console + CloudWatch dashboards rather than custom tooling.

## Cross-Cutting Implications Summary

The constraints above mostly point in one consistent direction:

> **Ultra-lean serverless on AWS Free Tier, single region (us-east-1), Cognito + Lambda + DynamoDB + S3+CloudFront + SES + minimal SNS, CDK in Python, monorepo with GitHub Actions, no VPC, no Aurora, no Fargate.**

Designs should default to that posture and only deviate when a clear technical need overrides it (with the deviation called out explicitly).
