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

            "true_positive": int,           # approve + success
            "true_negative": int,           # reject + failed
            "false_positive": int,          # approve + failed
            "false_negative": int,          # reject + success

            "precision": float | None,           # TP / (TP + FP)
            "recall": float | None,              # TP / (TP + FN)
            "false_positive_rate": float | None,  # FP / (FP + TN)
            "false_negative_rate": float | None,  # FN / (FN + TP)
        }

    accuracy_pct is None (never 0, never a fabricated number) when there
    is no verified data to compute a percentage from -- callers must
    render "N/A" in that case, not a misleading 0%. The same rule applies
    to precision/recall/false_positive_rate/false_negative_rate: each is
    None whenever its own denominator is 0, rather than a fabricated 0.
    """
    correct = 0
    incorrect = 0
    true_positive = 0
    true_negative = 0
    false_positive = 0
    false_negative = 0

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

        if decision == "approve" and deployment_status == "success":
            true_positive += 1
        elif decision == "reject" and deployment_status == "failed":
            true_negative += 1
        elif decision == "approve" and deployment_status == "failed":
            false_positive += 1
        elif decision == "reject" and deployment_status == "success":
            false_negative += 1

    total_verified = correct + incorrect
    accuracy_pct: Optional[float] = (correct / total_verified * 100) if total_verified > 0 else None

    precision: Optional[float] = (
        true_positive / (true_positive + false_positive) if (true_positive + false_positive) > 0 else None
    )
    recall: Optional[float] = (
        true_positive / (true_positive + false_negative) if (true_positive + false_negative) > 0 else None
    )
    false_positive_rate: Optional[float] = (
        false_positive / (false_positive + true_negative) if (false_positive + true_negative) > 0 else None
    )
    false_negative_rate: Optional[float] = (
        false_negative / (false_negative + true_positive) if (false_negative + true_positive) > 0 else None
    )

    return {
        "correct": correct,
        "incorrect": incorrect,
        "total_verified": total_verified,
        "accuracy_pct": accuracy_pct,
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
    }


def compute_daily_accuracy(rows: Iterable[dict]) -> list:
    """
    Same correctness definition as compute_approval_accuracy (reuses
    _is_correct / VERIFIABLE_DECISIONS / VERIFIED_STATUSES -- no
    duplicated business logic), grouped by calendar day taken from each
    row's "created_at" (audit_log stores this as an ISO 8601 string, e.g.
    "2026-07-19T14:32:07.481203" -- the first 10 characters are the date).

    Rows with a "delay" decision or an unverified deployment_status are
    skipped, exactly as in compute_approval_accuracy. A day with zero
    verified deployments is left out of the result entirely rather than
    reported as a fabricated 0%.

    Returns a list of {"date": "YYYY-MM-DD", "accuracy_pct": float},
    sorted by date ascending.
    """
    daily_counts: dict = {}  # date -> [correct, total]

    for row in rows:
        decision = row.get("decision")
        deployment_status = row.get("deployment_status")
        created_at = row.get("created_at")

        if decision not in VERIFIABLE_DECISIONS:
            continue
        if deployment_status not in VERIFIED_STATUSES:
            continue
        if not created_at:
            continue

        date = str(created_at)[:10]
        counts = daily_counts.setdefault(date, [0, 0])
        if _is_correct(decision, deployment_status):
            counts[0] += 1
        counts[1] += 1

    return [
        {"date": date, "accuracy_pct": correct / total * 100}
        for date, (correct, total) in sorted(daily_counts.items())
    ]
