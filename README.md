# ContriCool

Track shared transactions with friends — split expenses, settle balances, keep a clean audit trail. AWS-hosted, web-first with a single Expo + React Native + RN-Web codebase that ships to web today and iOS / Android tomorrow.

The repo is **public**. Treat every commit as a press release: no secrets, no environment-specific identifiers in source. See [`CLAUDE.md`](CLAUDE.md) for the project red lines and conventions.

---

## Status

**Phase 7 — Pre-launch polish.** Full execution plan: [`specs/EXECUTION_PLAN.md`](specs/EXECUTION_PLAN.md).

Functional scope of MVP:

- Sign up with email (phone is optional, unverified metadata).
- Add friends by exact email.
- Create transactions among friends with multiple split methods.
- List transactions; list with a specific friend; per-pair balances.
- Edit / delete / restore your own transactions.
- Account self-service: export your data (JSON, 1/day), delete your account (30-day grace, then hard-delete).
- Privacy Policy and Terms of Service shipped at `/privacy` and `/terms`.

Designs for every component are in [`specs/`](specs/).

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12+ | Use the shared venv at `/home/oshogupta/workspace/master-venv` (do not create a project-local venv) |
| Node | 22+ | LTS line |
| pnpm | 9+ | Activate via `corepack enable --install-directory ~/.local/bin` |
| AWS CLI | 2+ | For occasional read-only access; deploys go through CI |
| AWS CDK | 2+ | `pnpm dlx aws-cdk` works without a global install |
| `gh` | 2+ | GitHub CLI (used for PRs and repo settings) |
| `gitleaks` | 8+ | Required for pre-commit hooks. Install via `brew install gitleaks`, `apt install gitleaks`, or download from https://github.com/gitleaks/gitleaks/releases |
| `lefthook` | 1.8+ | Installed automatically via `pnpm install` |
| Docker | recent | For LocalStack during local dev (Phase 1+) |

---

## Local dev setup

```bash
# 1. Clone + cd in
gh repo clone GanAlps/contricool && cd contricool

# 2. Activate pnpm if you don't have it
corepack enable --install-directory ~/.local/bin
export PATH="$HOME/.local/bin:$PATH"

# 3. Install gitleaks (one of):
#    brew install gitleaks            # macOS
#    apt install gitleaks             # Ubuntu/Debian (may need a recent PPA)
#    go install github.com/gitleaks/gitleaks/v8@latest
# Verify: gitleaks version

# 4. Install JS deps and wire pre-commit hooks
make bootstrap
```

After `make bootstrap`, lefthook runs gitleaks on every `git commit` and a full-history scan on every `git push`. A commit containing an AWS access key, JWT, CloudFront default domain, API Gateway execute-api hostname, Cognito IDP URL, or AWS account ID in an ARN will be **blocked at the hook**.

If you hit an ergonomic gitleaks false-positive on an obviously-safe doc placeholder, **edit `.gitleaks.toml`'s `[allowlist]`** rather than committing with `--no-verify`. `--no-verify` is forbidden by repo policy — see `CLAUDE.md`.

---

## How the code is laid out (target — populated incrementally)

```
contricool/
  apps/
    api/              # FastAPI Lambda (Phase 1+)
    client/           # Expo + RN + RN-Web — auth screens deployed to S3+CloudFront (Phase 2d/2e)
    infra/            # AWS CDK in Python (Phase 1)
  packages/
    openapi/          # generated openapi.yaml (Phase 2e)
    client-sdk/       # generated TS SDK from openapi.yaml (Phase 2e)
  specs/              # design docs (read these first)
  .github/workflows/  # CI + deploy
  CLAUDE.md           # project red lines + conventions
  README.md           # this file
```

---

## How to deploy

Deploys are run **only** from GitHub Actions, never from a laptop. The flow:

1. Push a feature branch; open a PR.
2. CI runs (lint, test, gitleaks, `cdk diff` posted as PR comment).
3. After review, squash-merge to `main`.
4. The `deploy.yml` workflow auto-deploys to dev, runs smoke tests, then waits for manual approval (`prod` GitHub Environment).
5. Approve in the Actions UI to deploy to prod.

Rollback: `gh workflow run rollback.yml -f tag=<previous-tag>`.

End-to-end story is in `specs/EXECUTION_PLAN.md`; the OIDC + IAM setup is in `specs/03-hosting-infrastructure/design.md` and `specs/12-cicd-deployment/design.md`.

---

## Contributing

Everyone (human or agent) reads [`CLAUDE.md`](CLAUDE.md) first. Three red lines are non-negotiable:

1. No secrets / env identifiers in source.
2. Cost & abuse guardrails ship in CDK from day one.
3. Negative tests for auth and security gate every relevant PR.

PRs that violate any of these are rejected.
