"""Static checks on the GitHub Actions deploy + rollback workflow files.

These tests catch the kind of editing mistakes CI itself can't catch on a
PR — wrong role variable, missing OIDC permission, hardcoded ARN, missing
required-reviewer environment, etc. They're cheap and run on every PR.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_YAML = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
ROLLBACK_YAML = REPO_ROOT / ".github" / "workflows" / "rollback.yml"


@pytest.fixture(scope="module")
def deploy_workflow() -> dict[str, object]:
    with DEPLOY_YAML.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def rollback_workflow() -> dict[str, object]:
    with ROLLBACK_YAML.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# deploy.yml
# ---------------------------------------------------------------------------


def test_deploy_yaml_triggers_on_main_push_only(deploy_workflow: dict[str, object]) -> None:
    # PyYAML parses the YAML key `on:` as the Python boolean True.
    on = deploy_workflow.get(True) or deploy_workflow.get("on")
    assert isinstance(on, dict), f"Expected dict for `on:`; got {type(on).__name__}"
    assert "push" in on, "deploy.yml must trigger on push"
    push = on["push"]
    assert isinstance(push, dict)
    assert push.get("branches") == ["main"], (
        "deploy.yml must trigger only on push to main; "
        f"got branches={push.get('branches')!r}"
    )
    assert "pull_request" not in on, "deploy.yml must NOT trigger on PRs"


def test_deploy_yaml_serializes_via_concurrency(deploy_workflow: dict[str, object]) -> None:
    """Two merges must queue rather than overlap; CFN cannot run two
    parallel deploys against the same stack."""
    concurrency = deploy_workflow.get("concurrency")
    assert isinstance(concurrency, dict)
    assert concurrency.get("group") == "deploy-main"
    assert concurrency.get("cancel-in-progress") is False, (
        "cancel-in-progress must be False; deploy mid-flight should not be killed."
    )


def test_deploy_yaml_has_expected_job_chain(deploy_workflow: dict[str, object]) -> None:
    """The pipeline shape (dev → smoke → prod-gated → smoke → tag) is the
    contract; the test asserts each `needs:` link in order."""
    jobs = deploy_workflow["jobs"]
    assert isinstance(jobs, dict)
    expected_chain: dict[str, list[str]] = {
        "deploy-dev": [],
        "smoke-dev": ["deploy-dev"],
        "deploy-prod": ["smoke-dev"],
        "smoke-prod": ["deploy-prod"],
        "tag-release": ["smoke-prod"],
    }
    assert set(jobs.keys()) == set(expected_chain.keys()), (
        f"Unexpected job set: {sorted(jobs.keys())!r}"
    )
    for job_id, expected_needs in expected_chain.items():
        actual_needs = jobs[job_id].get("needs", [])
        if isinstance(actual_needs, str):
            actual_needs = [actual_needs]
        assert actual_needs == expected_needs, (
            f"{job_id}.needs={actual_needs!r}, expected {expected_needs!r}"
        )


def test_deploy_yaml_uses_oidc_roles_via_vars(deploy_workflow: dict[str, object]) -> None:
    """No hardcoded role ARN, no AWS_ACCESS_KEY_ID, only `vars.*` references."""
    raw = DEPLOY_YAML.read_text()
    # Red-line 1: never hardcoded role ARNs.
    assert "arn:aws:iam::" not in raw, (
        "deploy.yml must NOT hardcode IAM role ARNs; use vars.AWS_DEPLOY_ROLE_*"
    )
    # Red-line 1: never long-lived credentials.
    assert "AWS_ACCESS_KEY_ID" not in raw
    assert "AWS_SECRET_ACCESS_KEY" not in raw
    # Both deploy jobs must reference the right vars.
    assert "vars.AWS_DEPLOY_ROLE_DEV" in raw
    assert "vars.AWS_DEPLOY_ROLE_PROD" in raw
    assert "vars.AWS_REGION" in raw


def test_deploy_yaml_prod_job_uses_prod_environment(deploy_workflow: dict[str, object]) -> None:
    """deploy-prod must run inside the `prod` environment (gated by required reviewer)."""
    jobs = deploy_workflow["jobs"]
    assert jobs["deploy-prod"]["environment"] == "prod"
    # smoke-prod and tag-release also run under prod so they share the role
    # context and approval state.
    assert jobs["smoke-prod"]["environment"] == "prod"
    assert jobs["tag-release"]["environment"] == "prod"


def test_deploy_yaml_dev_jobs_use_dev_environment(deploy_workflow: dict[str, object]) -> None:
    jobs = deploy_workflow["jobs"]
    assert jobs["deploy-dev"]["environment"] == "dev"
    assert jobs["smoke-dev"]["environment"] == "dev"


def test_deploy_yaml_top_level_permissions_are_minimal(deploy_workflow: dict[str, object]) -> None:
    """Workflow-level permissions: only contents:read + id-token:write."""
    perms = deploy_workflow["permissions"]
    assert isinstance(perms, dict)
    assert perms.get("contents") == "read"
    assert perms.get("id-token") == "write"
    # Anything beyond these two is a smell at the workflow level — write
    # scopes should be per-job.
    extras = set(perms.keys()) - {"contents", "id-token"}
    assert not extras, f"Unexpected workflow-level permissions: {extras!r}"


def test_deploy_yaml_tag_release_has_contents_write(deploy_workflow: dict[str, object]) -> None:
    """Only the tag-release job should have contents:write (to push a tag)."""
    jobs = deploy_workflow["jobs"]
    tag_perms = jobs["tag-release"].get("permissions", {})
    assert tag_perms.get("contents") == "write", (
        "tag-release must have permissions.contents=write to push tags"
    )
    # No other job should grant contents:write.
    for job_id, job in jobs.items():
        if job_id == "tag-release":
            continue
        job_perms = job.get("permissions", {})
        assert job_perms.get("contents") != "write", (
            f"{job_id} must not grant contents:write"
        )


def test_deploy_yaml_documents_image_match_contract(
    deploy_workflow: dict[str, object],
) -> None:
    """The dev/prod image-match contract is enforced by CDK's content-
    addressed DockerImageAsset hashing — same source tree -> same digest
    -> ECR reuse. We removed the runtime ``Verify prod image == dev image``
    step because cross-job output propagation was flaky on the SHA value
    (run 25080974704). The comment block below documents why and how to
    restore a stronger check via SSM if ever needed; this test asserts
    that explanation stays in source so the next person doesn't quietly
    re-add the broken pattern."""
    # Normalise whitespace + leading comment markers so the assertion
    # tolerates the YAML wrapping of the comment block.
    raw = DEPLOY_YAML.read_text()
    flat = " ".join(line.lstrip("# ").strip() for line in raw.splitlines())
    assert "content-addressed DockerImageAsset hashing" in flat, (
        "deploy.yml must explain why the runtime image-match check was "
        "removed (CDK's content-addressed hashing IS the contract)"
    )
    # And the reintroduction-via-SSM hint.
    assert "SSM" in raw and "ssm:PutParameter" in raw, (
        "deploy.yml comment must point future maintainers at the SSM-based "
        "alternative if a runtime check is ever needed"
    )


# ---------------------------------------------------------------------------
# rollback.yml
# ---------------------------------------------------------------------------


def test_rollback_yaml_triggers_on_workflow_dispatch_only(
    rollback_workflow: dict[str, object],
) -> None:
    on = rollback_workflow.get(True) or rollback_workflow.get("on")
    assert isinstance(on, dict)
    assert "workflow_dispatch" in on
    assert "push" not in on
    assert "pull_request" not in on


def test_rollback_yaml_requires_tag_input(rollback_workflow: dict[str, object]) -> None:
    on = rollback_workflow.get(True) or rollback_workflow.get("on")
    assert isinstance(on, dict)
    dispatch = on["workflow_dispatch"]
    assert isinstance(dispatch, dict)
    inputs = dispatch.get("inputs", {})
    assert "tag" in inputs
    assert inputs["tag"]["required"] is True
    assert inputs["tag"]["type"] == "string"


def test_rollback_yaml_validates_tag_format(rollback_workflow: dict[str, object]) -> None:
    """Defense against typoed/garbage inputs."""
    raw = ROLLBACK_YAML.read_text()
    assert "release/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{7}" in raw, (
        "rollback.yml must validate the tag input matches the release/ format"
    )


def test_rollback_yaml_verifies_tag_on_main_ancestry(rollback_workflow: dict[str, object]) -> None:
    """Refuse to roll back to a tag that's not on main — protects against
    rollbacks to commits that were rebased off main or never merged."""
    raw = ROLLBACK_YAML.read_text()
    assert "git merge-base --is-ancestor" in raw


def test_rollback_yaml_uses_prod_role_and_environment(
    rollback_workflow: dict[str, object],
) -> None:
    """Same gating as deploy-prod."""
    jobs = rollback_workflow["jobs"]
    assert "rollback" in jobs
    assert jobs["rollback"]["environment"] == "prod"
    raw = ROLLBACK_YAML.read_text()
    assert "vars.AWS_DEPLOY_ROLE_PROD" in raw
    assert "arn:aws:iam::" not in raw
    assert "AWS_ACCESS_KEY_ID" not in raw


def test_rollback_yaml_serializes_with_deploy_yaml(rollback_workflow: dict[str, object]) -> None:
    """Same concurrency group as deploy.yml — never run a deploy and a
    rollback simultaneously on prod."""
    concurrency = rollback_workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency.get("group") == "deploy-main"
    assert concurrency.get("cancel-in-progress") is False


def test_rollback_yaml_smokes_after_deploy(rollback_workflow: dict[str, object]) -> None:
    """Don't trust the rollback CDK deploy alone — confirm prod actually
    serves traffic after the alias swap."""
    raw = ROLLBACK_YAML.read_text()
    assert "/v1/health" in raw
    assert "Smoke" in raw


def test_rollback_yaml_dereferences_annotated_tags(
    rollback_workflow: dict[str, object],
) -> None:
    """Annotated tags (created by ``deploy.yml``'s ``git tag -a``) point at
    a tag-object, not the underlying commit. ``git rev-parse refs/tags/X``
    returns the tag-object SHA, which ``merge-base --is-ancestor`` will
    always reject. The ``^{}`` peel suffix dereferences to the commit.
    Without this, every rollback fails the ancestry check."""
    raw = ROLLBACK_YAML.read_text()
    assert "^{}" in raw, (
        "rollback.yml must dereference annotated tags via ``^{}`` before "
        "passing to git merge-base — see commit history for the bug"
    )


def test_deploy_yaml_environment_keys_explicitly_present(
    deploy_workflow: dict[str, object],
) -> None:
    """Beyond asserting environment values, assert the key itself is
    present on every job that should be gated. Catches a 'someone deleted
    the line' regression that wouldn't be caught by an equality test alone
    (the equality test would emit a misleading KeyError instead of a
    clean assertion failure)."""
    jobs = deploy_workflow["jobs"]
    for job_id in ("deploy-dev", "smoke-dev", "deploy-prod", "smoke-prod", "tag-release"):
        assert "environment" in jobs[job_id], (
            f"{job_id} must declare an `environment:` key for OIDC + "
            f"approval-gate scoping"
        )


def _collect_run_blocks(workflow: dict[str, object]) -> list[tuple[str, str]]:
    """Walk the parsed-YAML structure and return ``(job_id, run_value)``
    for every multi-line ``run:`` step. Walking the loaded dict (not the
    raw text) is the only correct way to do this — a regex on the source
    text either over-reaches across YAML structure lines (greedy) or
    under-reaches (skips runs across step boundaries)."""
    blocks: list[tuple[str, str]] = []
    jobs = workflow.get("jobs", {})
    assert isinstance(jobs, dict)
    for job_id, job in jobs.items():
        assert isinstance(job, dict)
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            run = step.get("run")
            if isinstance(run, str) and "\n" in run:
                blocks.append((job_id, run))
    return blocks


def test_deploy_yaml_run_blocks_use_strict_bash(
    deploy_workflow: dict[str, object],
) -> None:
    """Every multi-line ``run:`` block in deploy.yml must open with
    ``set -euo pipefail`` so a partial failure aborts the step instead of
    silently continuing. This workflow touches prod; a silent partial
    failure could corrupt SSM state or yield a misleading 'green' run."""
    blocks = _collect_run_blocks(deploy_workflow)
    assert blocks, "deploy.yml has no multi-line run: blocks — test is invalid"
    for job_id, run in blocks:
        first_line = next(
            (ln.strip() for ln in run.splitlines() if ln.strip()),
            "",
        )
        assert first_line == "set -euo pipefail", (
            f"deploy.yml job '{job_id}': multi-line `run:` must start with "
            f"`set -euo pipefail`; got first line: {first_line!r}"
        )


def test_rollback_yaml_run_blocks_use_strict_bash(
    rollback_workflow: dict[str, object],
) -> None:
    """Same guarantee as the deploy.yml variant, applied to rollback.yml
    where it matters more — rollback runs touch prod by definition."""
    blocks = _collect_run_blocks(rollback_workflow)
    assert blocks, "rollback.yml has no multi-line run: blocks — test is invalid"
    for job_id, run in blocks:
        first_line = next(
            (ln.strip() for ln in run.splitlines() if ln.strip()),
            "",
        )
        assert first_line == "set -euo pipefail", (
            f"rollback.yml job '{job_id}': multi-line `run:` must start with "
            f"`set -euo pipefail`; got first line: {first_line!r}"
        )
