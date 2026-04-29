# Phase 2b — `app/core/` shared backend infrastructure — Tasks

Single-PR scope; tasks are sequenced by dependency.

## Phase A — Module skeletons + tests

- [ ] A1. Add deps to `apps/api/pyproject.toml`: `python-ulid>=2.7.0`,
      `boto3-stubs[ssm]>=1.35.0` (dev). Reinstall in master-venv.
- [ ] A2. Create `apps/api/app/core/__init__.py` (empty).
- [ ] A3. Create `apps/api/app/core/config.py` per design (AppConfig dataclass
      + `load()` + `_set_for_tests()`).
- [ ] A4. Create `apps/api/app/core/observability.py`: Powertools Logger +
      Metrics + Tracer + `_redact` recursive helper + denylist.
- [ ] A5. Create `apps/api/app/core/principal.py`: Pydantic v2 `Principal`
      model + `from_claims()` factory.
- [ ] A6. Create `apps/api/app/core/lookup_hash.py`: `email_hash()` HMAC-SHA-256.
- [ ] A7. Create `apps/api/app/core/policy.py`: `is_self()` +
      `NotImplementedError` placeholders for `is_friend()` /
      `can_edit_transaction()`.
- [ ] A8. Create `apps/api/app/core/middleware.py`: `CoreMiddleware` +
      `install_core_middleware()`.

## Phase B — Test infrastructure

- [ ] B1. Create `apps/api/tests/conftest.py` with shared fixtures:
      `seed_config`, `caplog_json`. Add `moto>=5.0.0` to dev deps.
- [ ] B2. `apps/api/tests/core/__init__.py`.
- [ ] B3. `apps/api/tests/core/test_config.py`:
      - `test_load_returns_app_config` (moto SSM stub, all 7 params)
      - `test_load_caches_after_first_call` (assert moto seen once)
      - `test_load_raises_on_missing_param` (param absent)
      - `test_load_raises_on_empty_param` (param value == "")
      - `test_set_for_tests_overrides_cache`
- [ ] B4. `apps/api/tests/core/test_observability.py`:
      - `test_redact_replaces_deny_keys_at_top_level`
      - `test_redact_recurses_into_nested_dicts`
      - `test_redact_recurses_into_lists`
      - `test_redact_is_case_insensitive`
      - `test_redact_matches_split_word_fragments` (e.g., `customer_email`
        redacts because of `email`)
      - `test_redact_passes_through_innocent_keys`
      - `test_redact_handles_pii_salt_key`
      - `test_logger_emits_valid_json`
- [ ] B5. `apps/api/tests/core/test_principal.py`:
      - `test_from_claims_happy_path`
      - `test_from_claims_missing_user_id_raises`
      - `test_from_claims_empty_email_raises`
      - `test_from_claims_invalid_token_use_raises`
      - `test_from_claims_groups_default_empty_list`
- [ ] B6. `apps/api/tests/core/test_lookup_hash.py`:
      - `test_hash_is_deterministic`
      - `test_hash_normalises_case_and_whitespace`
      - `test_hash_empty_input_raises`
      - `test_hash_non_string_input_raises`
      - `test_hash_output_is_64_char_lowercase_hex`
      - `test_hash_uses_configured_salt` (different salt → different hash)
- [ ] B7. `apps/api/tests/core/test_middleware.py`:
      - `test_request_id_echoed_in_response`
      - `test_invalid_request_id_replaced_with_ulid`
      - `test_request_state_request_id_populated`
      - `test_access_log_emitted_with_status_and_duration`
      - `test_access_log_redacts_password_in_body`
      - `test_access_log_does_not_log_query_string` (nothing logged)
      - `test_access_log_does_not_log_authorization_header`

## Phase C — Wire into main.py + verify

- [ ] C1. Refactor `apps/api/app/main.py` into `create_app()` that calls
      `config.load()` + `install_core_middleware()` + mounts existing
      `health` router. Keep `app = create_app()` at module bottom for
      Lambda Web Adapter.
- [ ] C2. Update existing `tests/test_health.py` to use a `client` fixture
      from conftest that builds an app from a `seed_config` fixture (so
      health tests don't hit SSM).
- [ ] C3. Run `make api-test` — full suite passes; coverage ≥ 99% on
      `apps/api/app/core/`.
- [ ] C4. Run `ruff check apps/api && mypy apps/api/app` — clean.
- [ ] C5. Run `gitleaks detect` — clean.

## Phase D — Spec + EXECUTION_PLAN updates

- [ ] D1. Update `specs/EXECUTION_PLAN.md`: mark 2e (`app/core/`) as
      shipped under the Phase 2b sub-phase row.
- [ ] D2. Open PR. Wait for green CI. Address pr-code-reviewer findings.
- [ ] D3. Merge after approval. Verify deploy.yml redeploys API Lambda
      cleanly and `/v1/health` still returns 200 (the only behavioural
      change to prod is the request-ID header in responses + extra
      cold-start cost ~50 ms for SSM).

## Out of scope (Phase 2c)

- JWT signature verification + JWKS caching.
- `current_principal()` FastAPI dependency.
- API Gateway HTTP API JWT authorizer wiring.
- Any `/v1/auth/*` endpoint.
- Any DDB I/O against `ContriCool-Users-<env>`.
