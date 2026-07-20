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


def compute_baseline_failure_rate(baseline_rows: Iterable[dict]) -> Optional[float]:
    """
    Failure rate in data/deployment_history.csv -- the 500-row synthetic
    "past company history" every deployment in this repo shipped with, all
    of it unfiltered by this tool (it predates the tool existing). Its
    "outcome" column uses "success"/"fail" (not the audit log's
    "deployment_status", which uses "success"/"failed").

    Returns None only if the input has no rows with a recognized outcome
    (i.e. someone points this at the wrong file) -- the real 500-row file
    always yields a real number, never a placeholder.
    """
    outcomes = [r.get("outcome") for r in baseline_rows if r.get("outcome") in ("success", "fail")]
    if not outcomes:
        return None
    return sum(1 for o in outcomes if o == "fail") / len(outcomes)


def compute_failure_rate_impact(audit_rows: Iterable[dict], baseline_rows: Iterable[dict]) -> dict:
    """
    Answers the brief's "reduction in failed deployments" evaluation
    criterion honestly, without waiting months for volume: compares the
    pre-tool baseline failure rate (deployment_history.csv, zero AI
    gating) against the real failure rate among deployments THIS TOOL
    approved that have since been verified (decision == "approve" and a
    real deployment_status from DEV-009's /deployment-verification).

    Deliberately excludes delayed/rejected deployments from the "actual"
    side -- this metric asks "of what the AI let through, how often did it
    actually break", not "how often did anything break", since delay/
    reject outcomes are governed by the Approval Accuracy metric instead.

    Returns:
        {
            "baseline_fail_rate": float | None,  # from the 500-row starter history
            "actual_fail_rate": float | None,    # None until >=1 approved deployment is verified
            "sample_size": int,                  # verified, approved deployments counted
            "reduction_pct": float | None,       # None until actual_fail_rate is known
        }

    reduction_pct is positive when the tool is doing better than baseline,
    negative when it's doing worse -- never fabricated, never clamped.
    """
    baseline_fail_rate = compute_baseline_failure_rate(baseline_rows)

    approved_verified = [
        row for row in audit_rows
        if row.get("decision") == "approve" and row.get("deployment_status") in VERIFIED_STATUSES
    ]
    sample_size = len(approved_verified)
    actual_fail_rate: Optional[float] = (
        sum(1 for row in approved_verified if row["deployment_status"] == "failed") / sample_size
        if sample_size > 0 else None
    )

    reduction_pct: Optional[float] = None
    if baseline_fail_rate is not None and actual_fail_rate is not None and baseline_fail_rate > 0:
        reduction_pct = (baseline_fail_rate - actual_fail_rate) / baseline_fail_rate * 100

    return {
        "baseline_fail_rate": baseline_fail_rate,
        "actual_fail_rate": actual_fail_rate,
        "sample_size": sample_size,
        "reduction_pct": reduction_pct,
    }
