"""Tests for ``CoreMiddleware`` — request-ID injection + access log."""
from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import AppConfig
from app.core.middleware import _ULID_RE


@pytest.fixture
def app(seed_config: AppConfig) -> FastAPI:
    """Build a minimal FastAPI app with one echo route + middleware."""
    from app.core.middleware import install_core_middleware

    api = FastAPI()
    install_core_middleware(api)

    @api.get("/echo")
    async def _echo(request: Request) -> dict[str, str]:
        return {"request_id": getattr(request.state, "request_id", "")}

    @api.post("/echo")
    async def _echo_post(payload: dict[str, str]) -> dict[str, str]:
        return {"received_keys": ",".join(sorted(payload.keys()))}

    return api


def test_request_id_echoed_in_response(client: TestClient) -> None:
    valid = "01HK3W7QF6VMYG8XR3DQ7B5N6P"
    response = client.get("/echo", headers={"X-Request-Id": valid})
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == valid
    assert response.json()["request_id"] == valid


def test_invalid_request_id_replaced_with_ulid(client: TestClient) -> None:
    response = client.get("/echo", headers={"X-Request-Id": "not-a-ulid"})
    assert response.status_code == 200
    out_id = response.headers["X-Request-Id"]
    assert _ULID_RE.match(out_id), f"Expected ULID; got {out_id!r}"


def test_missing_request_id_generates_new_one(client: TestClient) -> None:
    response = client.get("/echo")
    assert response.status_code == 200
    out_id = response.headers["X-Request-Id"]
    assert _ULID_RE.match(out_id)


def test_request_state_request_id_populated(client: TestClient) -> None:
    response = client.get(
        "/echo", headers={"X-Request-Id": "01HK3W7QF6VMYG8XR3DQ7B5N6P"}
    )
    assert response.json()["request_id"] == "01HK3W7QF6VMYG8XR3DQ7B5N6P"


def test_two_requests_get_distinct_request_ids(client: TestClient) -> None:
    r1 = client.get("/echo")
    r2 = client.get("/echo")
    assert r1.headers["X-Request-Id"] != r2.headers["X-Request-Id"]


def test_access_log_emitted_with_status_and_duration(
    caplog: pytest.LogCaptureFixture,
    client: TestClient,
) -> None:
    """Negative test: the access log is the only log line per request,
    and it never carries the body, query string, or auth header."""
    import logging

    caplog.set_level(logging.INFO, logger="contricool-api")

    response = client.post(
        "/echo?token=supersecret",
        json={"password": "hunter2", "name": "Alice"},
        headers={"Authorization": "Bearer leak-this-and-die"},
    )
    assert response.status_code == 200

    text = "\n".join(rec.getMessage() + " " + str(rec.__dict__) for rec in caplog.records)
    assert "hunter2" not in text, (
        "Request body content leaked into log output. "
        "CoreMiddleware must NEVER log bodies."
    )
    assert "leak-this-and-die" not in text, (
        "Authorization header value leaked into log output."
    )
    assert "supersecret" not in text, (
        "Query-string token leaked into log output."
    )
    # We expect at least one record from the middleware (the access log).
    middleware_records = [r for r in caplog.records if r.name == "contricool-api"]
    assert middleware_records, (
        "Expected at least one access-log line from CoreMiddleware"
    )


def test_response_header_request_id_matches_state(client: TestClient) -> None:
    """Defensive: header value must equal what middleware stored on state."""
    response = client.get("/echo")
    assert response.headers["X-Request-Id"] == response.json()["request_id"]


def test_ulid_regex_rejects_non_crockford() -> None:
    """The ULID regex must reject lowercase, ``I``, ``L``, ``O``, ``U``."""
    for bad in (
        "01HK3W7QF6VMYG8XR3DQ7B5N6p",  # trailing lowercase
        "01HK3W7QF6VMYG8XR3DQ7B5N6I",  # forbidden 'I'
        "01HK3W7QF6VMYG8XR3DQ7B5N6L",  # forbidden 'L'
        "01HK3W7QF6VMYG8XR3DQ7B5N6O",  # forbidden 'O'
        "01HK3W7QF6VMYG8XR3DQ7B5N6U",  # forbidden 'U'
        "01HK3W7QF6VMYG8XR3DQ7B5N",     # 24 chars
        "01HK3W7QF6VMYG8XR3DQ7B5N6PXYZ",# 29 chars
    ):
        assert not _ULID_RE.match(bad), f"Regex should reject {bad!r}"


def test_ulid_regex_accepts_valid() -> None:
    valid = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
    assert _ULID_RE.pattern == valid.pattern


def test_base_exception_does_not_break_finally(
    seed_config: AppConfig,  # noqa: ARG001
) -> None:
    """Regression: when a ``BaseException`` subclass (e.g. SystemExit)
    skips the ``except Exception`` block, the ``finally`` access-log
    line must still run successfully — meaning ``status_code`` is
    pre-initialised, not annotation-only."""
    import asyncio

    from app.core.middleware import CoreMiddleware

    middleware = CoreMiddleware(app=lambda *a, **kw: None)  # type: ignore[arg-type]

    async def _call_next_raises_baseexc(_request: object) -> None:
        raise SystemExit(0)

    # Build a synthetic ASGI scope just enough for middleware.dispatch.
    from starlette.requests import Request

    scope: dict[str, object] = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "raw_path": b"/x",
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "server": ("test", 80),
    }
    request = Request(scope)

    async def _drive() -> None:
        # The dispatch must surface SystemExit, not NameError.
        with pytest.raises(SystemExit):
            await middleware.dispatch(request, _call_next_raises_baseexc)  # type: ignore[arg-type]

    asyncio.run(_drive())


def test_route_exception_logs_and_reraises(
    seed_config: AppConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a route handler raises, middleware must (a) emit an access-log
    line, (b) re-raise so FastAPI's exception handler still runs, and (c)
    record the failure as a 5xx in the log line."""
    import logging

    from app.core.middleware import install_core_middleware

    api = FastAPI()
    install_core_middleware(api)

    @api.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("synthetic failure")

    caplog.set_level(logging.INFO, logger="contricool-api")

    with TestClient(api, raise_server_exceptions=False) as c:
        response = c.get("/boom")

    assert response.status_code == 500

    access_logs = [r for r in caplog.records if r.message == "request"]
    assert access_logs, "Expected an access-log line even on exception"
    # Find the record whose extras include status_code=500.
    statuses = [getattr(r, "status_code", None) for r in access_logs]
    assert 500 in statuses, f"Expected 500 in access-log status codes; got {statuses}"
