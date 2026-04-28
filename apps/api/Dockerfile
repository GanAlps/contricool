# ContriCool API — Lambda container image (arm64).
#
# Uses the AWS Lambda Web Adapter as a runtime extension so the same uvicorn
# entry point runs locally and inside Lambda (Design 2 — "Mangum vs LWA"
# decided LWA for dev/prod parity).

FROM public.ecr.aws/docker/library/python:3.12-slim

# AWS Lambda Web Adapter — extension binary; Lambda runtime auto-picks up
# anything in /opt/extensions/.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV PORT=8080 \
    READINESS_CHECK_PATH=/v1/health \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps. Pin matches apps/api/pyproject.toml.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi==0.115.4" \
        "uvicorn==0.32.0" \
        "aws-lambda-powertools[parser,tracer]==3.3.0" \
        "pydantic==2.9.2"

# App source.
COPY app ./app

EXPOSE 8080

# uvicorn runs as PID 1; LWA forwards Lambda events to localhost:8080.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
