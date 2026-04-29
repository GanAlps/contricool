# ContriCool API — Lambda container image (arm64).
#
# Uses the AWS Lambda Web Adapter as a runtime extension so the same uvicorn
# entry point runs locally and inside Lambda (Design 2 — "Mangum vs LWA"
# decided LWA for dev/prod parity).

# Pin the base image by digest so rollback to a previous source rebuilds
# the byte-identical image (and CDK's content-addressed asset hash stays
# stable across re-pulls). When updating Python, bump both the tag and the
# digest in the same PR. To resolve a fresh digest:
#   docker pull public.ecr.aws/docker/library/python:3.12-slim
#   docker inspect --format='{{index .RepoDigests 0}}' \
#     public.ecr.aws/docker/library/python:3.12-slim
FROM public.ecr.aws/docker/library/python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3

# AWS Lambda Web Adapter — extension binary; Lambda runtime auto-picks up
# anything in /opt/extensions/.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV PORT=8080 \
    READINESS_CHECK_PATH=/v1/health \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps. Pins must match the runtime ``[project] dependencies``
# block in apps/api/pyproject.toml — drift here is caught by
# ``apps/api/tests/test_dockerfile_deps.py``. The previous shorter list
# silently shipped images without ``boto3`` once Phase 2c started using
# it at cold start, breaking every Lambda invocation.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi==0.115.4" \
        "uvicorn==0.32.0" \
        "aws-lambda-powertools[parser,tracer]==3.3.0" \
        "pydantic[email]==2.9.2" \
        "boto3>=1.35.0" \
        "python-ulid>=2.7.0" \
        "pyjwt[crypto]>=2.9.0" \
        "cryptography>=43.0.0"

# App source.
COPY app ./app

EXPOSE 8080

# uvicorn runs as PID 1; LWA forwards Lambda events to localhost:8080.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
