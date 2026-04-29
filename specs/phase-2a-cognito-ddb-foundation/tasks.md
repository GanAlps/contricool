# Phase 2a — Cognito + DynamoDB + PII salt CDK foundation — Tasks

Tasks are grouped into three small phases. Each phase ends with a green test
run before the next begins.

---

## Phase A — Auth Stack (Cognito + PII salt)

- [ ] A1. Create `apps/infra/constructs/__init__.py`.
- [ ] A2. Create `apps/infra/constructs/pii_salt_handler.py` —
      Lambda handler module: `handler(event, context)` switching on
      `RequestType` ∈ {Create, Update, Delete}; on Create, calls
      `ssm.put_parameter(Type=SecureString, Overwrite=False, KeyId=...)` with
      `secrets.token_hex(32)`; tolerates `ParameterAlreadyExists`; on Update +
      Delete is a no-op. Returns `PhysicalResourceId = parameter Name`.
- [ ] A3. Create `apps/infra/constructs/pii_salt.py` — `PiiSalt` construct
      that wraps a `Provider` (`aws_cdk.aws_lambda.Function` from
      `pii_salt_handler.py`) + a `CustomResource`. Construct accepts
      `parameter_name`, `kms_key_arn` (optional). Provider Lambda has
      reserved_concurrency=1 (it runs once per deploy at most).
- [ ] A4. Create `apps/infra/stacks/auth_stack.py` — `AuthStack(env_name,
      prod_cmk)` building User Pool + 3 App Clients + `PiiSalt` construct.
      Add CfnOutputs for UserPoolId, three ClientIds.
- [ ] A5. Wire `AuthStack` into `apps/infra/app.py` per env (parallel to
      existing Api/Web/Monitoring); add `cdk.Tags.of(auth).add("env", env)`.
- [ ] A6. Tests in `apps/infra/tests/test_synth.py`:
      - `test_auth_stack_user_pool_email_only_no_sms_no_mfa`
      - `test_auth_stack_password_policy_meets_design_4`
      - `test_auth_stack_custom_user_id_attribute`
      - `test_auth_stack_three_clients_no_secret_with_srp_only`
      - `test_auth_stack_token_lifetimes_match_design_4`
      - `test_auth_stack_pii_salt_provider_uses_kms_in_prod_only`
      - `test_auth_stack_user_pool_retention_in_prod_destroy_in_dev`
      - `test_auth_stack_account_recovery_email_only`
- [ ] A7. Tests in `apps/infra/tests/test_aspects.py`:
      - The PII-salt provider Lambda either has reserved_concurrency set or
        is in the SecurityAspect exemption list. Construct-path-based
        exemption is preferred.
- [ ] A8. Run `make infra-test` — all Phase-A tests green; existing tests
      still green; coverage on `apps/infra/` ≥ 99%.

## Phase B — Data Stack (Users DDB)

- [ ] B1. Create `apps/infra/stacks/data_stack.py` — `DataStack(env_name,
      prod_cmk)` building `ContriCool-Users-<env>` table with PK/SK + GSI1 +
      TTL + PITR/Streams/CMK conditional on prod.
- [ ] B2. Wire `DataStack` into `apps/infra/app.py` per env; tag.
- [ ] B3. Tests in `apps/infra/tests/test_synth.py`:
      - `test_data_stack_table_keys_billing_ttl`
      - `test_data_stack_gsi1_keys_and_projection_all`
      - `test_data_stack_pitr_streams_only_in_prod`
      - `test_data_stack_kms_cmk_in_prod_default_in_dev`
      - `test_data_stack_users_table_retention_in_prod_destroy_in_dev`
      - `test_data_stack_table_name_matches_design_7`
- [ ] B4. Run `make infra-test` — all green; coverage ≥ 99%.

## Phase C — Deploy + verify

- [ ] C1. Update `.github/workflows/deploy.yml` — extend the "Capture deploy
      outputs" step in `deploy-dev` and `deploy-prod` to also fetch
      `Contricool-<Env>-Auth.{UserPoolId,WebClientId,IosClientId,AndroidClientId}`
      and `Contricool-<Env>-Data.UsersTableName` and `aws ssm put-parameter`
      them under `/contricool/<env>/cognito/*` + `/contricool/<env>/ddb/*`.
- [ ] C2. Tests in `apps/infra/tests/test_deploy_workflow_yaml.py`:
      - `test_deploy_workflow_writes_cognito_ids_to_ssm` — assert each env's
        deploy job has the expected 5 SSM puts (4 Cognito + 1 DDB).
      - `test_deploy_workflow_does_not_write_pii_salt` — regression for
        red-line 1 (salt is owned by the custom resource).
- [ ] C3. Update `specs/EXECUTION_PLAN.md` — mark 2a/2b/2c rows as PR-pending.
- [ ] C4. Update `CLAUDE.md` Section 2 (one-page summary) — add line about
      the new Auth + Data stacks now existing per env.
- [ ] C5. Run `make lint && make infra-test`. Then `gitleaks detect` on the
      branch — clean.
- [ ] C6. Open PR. Wait for CI green. Merge via squash. Pipeline rolls
      through dev → smoke → prod gate → prod → smoke → tag.
- [ ] C7. Manual verification on dev:
      - `aws cognito-idp describe-user-pool --user-pool-id $(aws ssm get-parameter --name /contricool/dev/cognito/user-pool-id --query Parameter.Value --output text)`
        → returns the pool with Email-only auto-verify, Mfa OFF, no
        `SmsConfiguration`.
      - `aws dynamodb describe-table --table-name ContriCool-Users-dev` →
        `BillingMode=PAY_PER_REQUEST`, GSI1 present, TTL on `ttl`.
      - `aws ssm get-parameter --name /contricool/dev/pii-salt --with-decryption`
        → 64-char hex string.
- [ ] C8. After prod gate approval: same three checks on prod, plus PITR
      enabled and `StreamSpecification` on the Users table.
- [ ] C9. Mark Phase 2a complete in `specs/EXECUTION_PLAN.md`.

## Out of scope (handled in Phase 2b/2c)

- API Gateway JWT authorizer pointed at the new pool.
- Cognito user-pool triggers (PreSignUp, PostConfirmation).
- Lambda execution role grants for `cognito-idp:*` and DDB read/write — added
  with the auth feature in Phase 2c.
- Frontend bootstrap — Phase 2d.
