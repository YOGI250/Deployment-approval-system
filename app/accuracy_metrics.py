"""
accuracy_metrics.py

Purpose: IMP-001 -- computes AI prediction accuracy from real, verified
deployment outcomes only. Nothing here is hardcoded, estimated, or
guessed -- every number comes from counting actual audit_log rows
(decision + deployment_status, the latter written by DEV-009's
POST /deployment-verification once GET /health has actually run).

Correctness definition (exactly as specified by the ticket):
    decision == "approve" and deployment_status == "success"  -> correct
    decision == "reject"  and deployment_status == "failed"   -> correct
    decision == "approve" and deployment_status == "failed"   -> incorrect
    decision == "reject"  and deployment_status == "success"  -> incorrect

A row is excluded from the calculation entirely (counted as neither
correct nor incorrect) when:
  - deployment_status isn't "success" or "failed" -- no post-deployment
    health verification has run for that deployment yet. "Ignore that
    record" per the ticket, rather than guess at an outcome.
  - decision == "delay". The ticket only defines correctness for
    Approve/Reject; a delayed deployment doesn't have a defined
    "correct AI call" to compare against without inventing semantics
    the ticket never specified, so it's left out rather than guessed at.
"""

from typing import Iterable, Optional

VERIFIABLE_DECISIONS = {"approve", "reject"}
VERIFIED_STATUSES = {"success", "failed"}


def _is_correct(decision: str, deployment_status: str) -> bool:
    return (
        (decision == "approve" and deployment_status == "success")
        or (decision == "reject" and deployment_status == "failed")
    )


def compute_approval_accuracy(rows: Iterable[dict]) -> dict:
    """
    rows: audit log rows (as returned by audit_log.get_all_logs(), or the
    equivalent dicts the API's /history response produces) -- each is
    expected to carry "decision" and "deployment_status" keys, though
    rows missing either are simply excluded rather than raising.

    Returns:
        {
            "correct": int,
            "incorrect": int,
            "total_verified": int,
            "accuracy_pct": float | None,   # None when total_verified == 0
        }

    accuracy_pct is None (never 0, never a fabricated number) when there
    is no verified data to compute a percentage from -- callers must
    render "N/A" in that case, not a misleading 0%.
    """
    correct = 0
    incorrect = 0

    for row in rows:
        decision = row.get("decision")
        deployment_status = row.get("deployment_status")

        if decision not in VERIFIABLE_DECISIONS:
            continue
        if deployment_status not in VERIFIED_STATUSES:
            continue

        if _is_correct(decision, deployment_status):
            correct += 1
        else:
            incorrect += 1

    total_verified = correct + incorrect
    accuracy_pct: Optional[float] = (correct / total_verified * 100) if total_verified > 0 else None

    return {
        "correct": correct,
        "incorrect": incorrect,
        "total_verified": total_verified,
        "accuracy_pct": accuracy_pct,
    }
