<!-- Conventional commit subject style: feat: ..., fix: ..., chore: ..., refactor: ..., test: ..., docs: ... -->

## What changed

<!-- One or two sentences. Keep it tight. -->

## Why

<!-- The motivation. Link to specs/ if relevant. -->

## Phase + design references

<!-- Which phase from specs/EXECUTION_PLAN.md and which design doc(s) does this implement? -->
- Phase: <!-- e.g. Phase 2.d backend auth feature -->
- Design: <!-- e.g. specs/04-authentication/design.md, specs/07-database-data-model/design.md -->

## Red-line checklist (RED LINES from CLAUDE.md)

- [ ] No secrets, AWS account IDs, CloudFront domains, API Gateway IDs, Cognito pool IDs, or other env-specific identifiers in source.
- [ ] All new cost-or-abuse-sensitive paths have caps / rate limits / alarms wired in CDK in this PR (or aren't introduced here).
- [ ] If this touches auth, authorization, rate limiting, validation, or PII handling, **negative tests** for the failure paths are included.

## Test evidence

<!-- Paste test counts, coverage %, or screenshots of green CI. -->
