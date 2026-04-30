# Phase 6 — Observability + Ops Hardening — Design

## Overview

Phase 6 turns the Phase 1 alarm scaffolding into the production-grade
monitoring surface from Design 11, plus the frontend telemetry
pipeline + runbooks.

## Backend

- New `app/features/telemetry` module (no DDB / no Cognito):
  `POST /v1/telemetry/error` accepts `{ level: 'error'|'metric',
  name, message?, stack?, url?, user_agent?, value?, extra? }` and
  logs the structured event into CloudWatch via the powertools
  logger. Public route (auth-bootstrap-only path); per-route
  throttling caps the log spend at 10 RPS / 20 burst.
- `app/main.py` mounts the telemetry router under `/v1`.

## CDK

- `MonitoringStack` extended:
  - 7 simple alarms (lambda-errors, lambda-throttles,
    lambda-duration-p95, apigw-5xx, apigw-4xx-burst,
    ddb-throttle-users, ddb-throttle-transactions).
  - 1 composite "site-is-down" alarm that wraps lambda-errors OR
    apigw-5xx — the only alarm that pages oncall via SMS.
  - Prod dashboard expanded with throttle + duration percentile
    widgets + an alarm-status panel.
  - 6 saved Logs Insights queries via `CfnQueryDefinition` (the L2
    `QueryString` requires field-decomposition that doesn't
    round-trip our hand-written Insights queries).
- `ApiStack`:
  - `/v1/telemetry/error` added to `_PUBLIC_AUTH_PATHS` (no JWT)
    and to `_ROUTE_THROTTLES` at 10 RPS / 20 burst.

## Frontend

- `lib/telemetry.ts` — `postTelemetry`, `reportError`, `reportMetric`
  helpers. Dedup at 200 ms per (level, name). `keepalive: true` on
  the `fetch` so the request survives a page-unload right after a
  crash. Swallows errors so telemetry never crashes the page.
- `components/ErrorBoundary.tsx` — class-based React error
  boundary with friendly retry card; posts to telemetry on every
  caught error. Plus `installGlobalErrorTelemetry()` for
  `unhandledrejection` + `error` window events.
- `lib/web-vitals.ts` — dynamic-import wrapper around the
  `web-vitals` package (web-only; native bundle never loads it).
  Subscribes LCP/INP/CLS/FCP/TTFB to the metric sink.
- `app/_layout.tsx` — wraps the app in `ErrorBoundary`, calls
  `installGlobalErrorTelemetry()` + `reportWebVitals()` on mount.

## Runbooks

`specs/runbooks/`:

- `runbook-5xx.md`
- `runbook-ddb-throttle.md`
- `runbook-sms-spend.md`
- `runbook-rollback.md`
- `runbook-pitr-restore.md`

## Out of scope

- **WAF rate-based rule for telemetry** — APIGW route-level
  throttling caps stage-wide, not per-IP. WAF construct is a
  Phase 7 deliverable. The current ceiling is 10 RPS / 20 burst,
  which already protects log-spend at MVP scale.
- **Alarm-firing test** — manual verification only; the alarm
  resources are CDK-validated via the existing synth tests.
- **Frontend RUM via CloudWatch RUM** — `web-vitals` is the
  lighter approach; CloudWatch RUM requires an app-monitor + IAM
  setup that we don't need at MVP.

## Coverage

- Backend: 99% floor (current 99.03%).
- Client thresholds preserved.
