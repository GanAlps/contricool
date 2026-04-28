# apps/api — FastAPI Lambda backend

Python 3.12 + FastAPI on AWS Lambda (arm64 container image). Runs via uvicorn behind the **AWS Lambda Web Adapter** so the same `uvicorn app.main:app --host 0.0.0.0 --port 8080` command runs locally and inside Lambda (Design 2).

## Phase 1 surface

Just one route: `GET /v1/health` — liveness check, side-effect-free, unauthenticated. Used by the deploy smoke-test step.

## Local development

```bash
cd apps/api
pip install -e .[dev]
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
# In another terminal:
curl http://localhost:8080/v1/health
```

## Tests

```bash
pytest --cov=app --cov-fail-under=99
```

The `--cov-fail-under=99` matches the CLAUDE.md coverage floor; Phase 1's surface is small enough that 99% on `app/` is met by the three tests in `tests/test_health.py`.

## Container image

`Dockerfile` is built by CDK's `DockerImageAsset` (apps/infra/stacks/api_stack.py). `linux/arm64` platform; the CDK aspect enforces `ReservedConcurrentExecutions=100` on the resulting Lambda.

## Layout

```
apps/api/
  app/
    main.py           # FastAPI app instance + router includes
    routes/
      health.py       # /v1/health
    features/         # (Phase 2+) auth, friends, transactions, notifications
    core/             # (Phase 2+) config, ddb client, cognito client, principal, policy
  tests/
    test_health.py
  Dockerfile
  pyproject.toml
  README.md
```

`features/` and `core/` directories appear when the corresponding domain code lands; we don't pre-create empty folders.
