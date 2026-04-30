"""Daily cleanup Lambda for the transactions feature.

Triggered by an EventBridge cron (``0 2 * * ? *`` UTC). For every
META row whose ``deleted_at`` is more than ``RESTORE_WINDOW_DAYS`` in
the past:

1. Hard-delete the META + MEMBER rows (BatchWriteItem).
2. Set ``ttl`` on every AUDIT row to ``now + AUDIT_RETENTION_DAYS``
   so DDB's TTL service purges the audit trail post-grace.

Per CLAUDE.md red-line 2, the IAM role for this Lambda is scoped
narrowly: ``dynamodb:Scan/Query/UpdateItem/BatchWriteItem`` on the
Transactions table only — no Users-table access, no Cognito access.

The handler is deliberately small and deterministic: a single Scan
pass capped at ``MAX_PER_INVOCATION``. If more than that need
cleanup the next day's run picks up the residue. We accept that
soft-deletes more than 30 days old may sit a few days longer; the
contract is "they are unreachable", not "they are byte-erased
exactly at the 30-day mark".
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.observability import logger
from app.features.transactions import repository as repo
from app.features.transactions import service as txn_service

# A second grace window for AUDIT rows: keeps the audit trail
# discoverable for support / abuse triage for 90 days after the
# transaction's content is hard-deleted.
AUDIT_RETENTION_DAYS = 90

# Per-invocation cap so the Lambda finishes well within its budget
# even on a backlog. Soft-deletes are rare at MVP scale, so this is
# unlikely to ever bind in practice.
MAX_PER_INVOCATION = 100


def _restore_cutoff_iso() -> str:
    """Return the ISO timestamp older than which a soft-deleted txn
    is past the 30-day restore window."""
    cutoff = datetime.now(UTC) - timedelta(
        days=txn_service.RESTORE_WINDOW_DAYS
    )
    return cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cleanup_once() -> dict[str, int]:
    """Single cleanup pass.

    Returns a small summary so the Lambda invocation log shows
    progress without dumping per-txn details.
    """
    cutoff_iso = _restore_cutoff_iso()
    candidates = repo.scan_soft_deleted(
        deleted_before_iso=cutoff_iso, limit=MAX_PER_INVOCATION
    )
    hard_deleted = 0
    audit_rows_marked = 0
    for meta in candidates:
        repo.hard_delete_transaction(meta.txn_id, meta.member_ids)
        n = repo.set_audit_ttl_for_purge(
            meta.txn_id, ttl_seconds_from_now=AUDIT_RETENTION_DAYS * 86400
        )
        audit_rows_marked += n
        hard_deleted += 1
    logger.info(
        "txn_cleanup_run",
        extra={
            "cutoff": cutoff_iso,
            "hard_deleted": hard_deleted,
            "audit_rows_marked": audit_rows_marked,
            "candidates": len(candidates),
        },
    )
    return {
        "candidates": len(candidates),
        "hard_deleted": hard_deleted,
        "audit_rows_marked": audit_rows_marked,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, dict[str, int]]:
    """EventBridge-shaped Lambda entrypoint.

    Runs both cleanup passes (transactions + deactivated accounts)
    and returns a structured summary so the invocation log shows
    progress for each.
    """
    from app.cleanup import accounts as accounts_cleanup

    return {
        "transactions": cleanup_once(),
        "accounts": accounts_cleanup.cleanup_accounts_once(),
    }
