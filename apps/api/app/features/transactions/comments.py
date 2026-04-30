"""Pure helpers for transaction comments.

The DDB writes for COMMENT rows live in
:mod:`app.features.transactions.repository`; this module hosts the
shape-agnostic logic — currently the system-comment diff summary used
when a transaction is edited.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _str(value: object) -> str:
    if isinstance(value, Decimal):
        # Avoid scientific notation for "100" → "1E+2"; Decimal.__str__
        # is well-defined for our inputs (always quantised to 2dp on
        # the persisted META row).
        return format(value, "f")
    return str(value)


def _format_member_set_diff(
    *, prior: list[str], current: list[str]
) -> str | None:
    """Return a "added X, removed Y" line, or None if no change."""
    prior_set = set(prior)
    current_set = set(current)
    added = sorted(current_set - prior_set)
    removed = sorted(prior_set - current_set)
    if not added and not removed:
        return None
    parts: list[str] = []
    if added:
        parts.append("added " + ", ".join(added))
    if removed:
        parts.append("removed " + ", ".join(removed))
    return "members: " + "; ".join(parts)


def _payers_match(
    prior_payers: list[dict[str, Any]], new_payers: list[dict[str, Any]]
) -> bool:
    """True iff the two payer lists carry the same set of (user, amount)
    pairs. Order is not significant."""

    def _key(p: dict[str, Any]) -> tuple[str, str]:
        return (str(p.get("user_id")), _str(p.get("paid_amount")))

    return sorted(_key(p) for p in prior_payers) == sorted(
        _key(p) for p in new_payers
    )


_LABELS = {
    "name": "name",
    "type": "type",
    "amount": "amount",
    "currency": "currency",
    "txn_date": "date",
    "note": "note",
    "split_method": "split method",
}


def build_edit_summary(
    *,
    prior_snapshot: dict[str, Any],
    new_inputs: dict[str, Any],
) -> str | None:
    """Produce a human-readable diff for the system comment.

    ``prior_snapshot`` is the META snapshot already captured by the
    update path (see :func:`service._meta_to_snapshot`).
    ``new_inputs`` are the post-update values (``name``, ``type``,
    ``amount``, ``currency``, ``txn_date``, ``note``, ``split_method``,
    ``payers``, ``members`` — the last as a list of user_ids).

    Returns ``None`` when nothing user-visible has changed (a "no-op
    edit"). The caller suppresses the system comment in that case so
    the comment thread does not fill with empty rows.
    """
    lines: list[str] = []
    for key, label in _LABELS.items():
        before = prior_snapshot.get(key)
        after = new_inputs.get(key)
        if before is None and after is None:
            continue
        if _str(before) == _str(after):
            continue
        lines.append(f"- {label}: {_str(before)} → {_str(after)}")

    member_line = _format_member_set_diff(
        prior=list(prior_snapshot.get("member_ids") or []),
        current=list(new_inputs.get("member_ids") or []),
    )
    if member_line:
        lines.append("- " + member_line)

    if not _payers_match(
        list(prior_snapshot.get("payers") or []),
        list(new_inputs.get("payers") or []),
    ):
        lines.append("- payers: changed")

    if not lines:
        return None
    return "Updated transaction:\n" + "\n".join(lines)


COMMENT_BODY_MIN = 1
COMMENT_BODY_MAX = 1000
COMMENT_LIST_DEFAULT = 50
COMMENT_LIST_MAX = 100
SYSTEM_AUTHOR = "system"
