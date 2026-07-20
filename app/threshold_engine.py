"""
threshold_engine.py

Deterministic calibration layer that sits between policy_engine and the
decision engine: checks whether a deployment's current risk level (after
the ML prediction and any mandatory policy override) actually meets the
bar data/risk_thresholds.json defines for that tier, and escalates one
level if it doesn't.

This is what makes risk_thresholds.json -- and adjust_thresholds.py,
which tightens/loosens it based on real audit-log fail rates -- a real,
decision-affecting mechanism. Before this module existed, those
thresholds were only ever passed to Groq as explanation context and had
zero effect on the actual risk_level/decision, which undercut the
brief's "adjust risk thresholds dynamically based on pipeline
performance" requirement: adjust_thresholds.py could tighten the Low bar
all it wanted and not one real decision would change. Now, tightening
the file directly makes escalation out of Low/Medium more likely; a
weekly scheduled retrain+recalibrate (see scheduled_maintenance.py) has
real teeth.

Runs after policy_engine deliberately: policy_engine's rules are
mandatory enterprise safety gates and must win outright (e.g. production
+ failing tests -> High, no exceptions); threshold calibration is a
softer "does this deployment even meet today's bar for the tier it
landed in" check layered on top of whatever policy already decided.

Never calls Groq. Never calls FastAPI. Takes a deployment dict, a
risk_level to check, and the parsed thresholds config -- returns a plain
dict, same contract shape as policy_engine.evaluate_policies(), so
risk_scorer.py can chain the two the same way.
"""

import logging

logger = logging.getLogger("threshold_engine")

RISK_LEVELS = ["Low", "Medium", "High"]


def _escalate_one_level(risk_level: str) -> str:
    if risk_level not in RISK_LEVELS:
        return risk_level
    idx = RISK_LEVELS.index(risk_level)
    return RISK_LEVELS[min(idx + 1, len(RISK_LEVELS) - 1)]


def _violations(deployment: dict, bounds: dict) -> list:
    """Returns one human-readable reason per bound this deployment fails
    for its current tier, or [] if it meets every bound thresholds.json
    defines for that tier. A bound is skipped (not a violation) when the
    deployment doesn't carry that field at all -- an unknown value can't
    be judged against a bar, so it fails toward "no violation" rather
    than guessing."""
    reasons = []

    max_files_changed = bounds.get("max_files_changed")
    files_changed = deployment.get("files_changed")
    if max_files_changed is not None and files_changed is not None and files_changed > max_files_changed:
        reasons.append(f"{files_changed} files changed exceeds this tier's maximum of {max_files_changed}")

    min_test_coverage_pct = bounds.get("min_test_coverage_pct")
    test_coverage_pct = deployment.get("test_coverage_pct")
    if min_test_coverage_pct is not None and test_coverage_pct is not None and test_coverage_pct < min_test_coverage_pct:
        reasons.append(f"test coverage {test_coverage_pct}% is below this tier's minimum of {min_test_coverage_pct}%")

    max_tests_failed = bounds.get("max_tests_failed")
    tests_failed = deployment.get("tests_failed")
    if max_tests_failed is not None and tests_failed is not None and tests_failed > max_tests_failed:
        reasons.append(f"{tests_failed} failed test(s) exceeds this tier's maximum of {max_tests_failed}")

    min_author_success_rate = bounds.get("min_author_success_rate")
    author_success_rate = deployment.get("author_recent_success_rate")
    if (
        min_author_success_rate is not None
        and author_success_rate is not None
        and author_success_rate < min_author_success_rate
    ):
        reasons.append(
            f"author recent success rate {author_success_rate} is below this tier's minimum of {min_author_success_rate}"
        )

    return reasons


def evaluate_thresholds(deployment: dict, risk_level: str, thresholds: dict) -> dict:
    """
    Input:
        deployment: the raw deployment dict (files_changed, test_coverage_pct,
            tests_failed, author_recent_success_rate, ...)
        risk_level: the risk level to check -- the ML prediction, or the
            policy-adjusted level if policy_engine already overrode it
        thresholds: risk_thresholds.json's parsed content -- {"low": {...}, "medium": {...}}

    Output: same shape as policy_engine.evaluate_policies() --
        {"risk_level": ..., "overridden": bool, "override_reason": str|None, "thresholds_triggered": [...]}

    Only Low and Medium have bounds to check against -- High is already
    the ceiling, nothing to escalate to. A deployment failing ANY bound
    for its current tier is escalated exactly one level.
    """
    bounds = thresholds.get(risk_level.lower()) if risk_level in ("Low", "Medium") else None

    if not bounds:
        return {"risk_level": risk_level, "overridden": False, "override_reason": None, "thresholds_triggered": []}

    reasons = _violations(deployment, bounds)
    if not reasons:
        return {"risk_level": risk_level, "overridden": False, "override_reason": None, "thresholds_triggered": []}

    escalated = _escalate_one_level(risk_level)
    logger.info(
        "Threshold calibration escalated %s -> %s: %s",
        risk_level, escalated, "; ".join(reasons),
    )
    return {
        "risk_level": escalated,
        "overridden": True,
        "override_reason": (
            f"Deployment landed in {risk_level} but doesn't meet the current {risk_level} threshold bar: "
            + "; ".join(reasons)
        ),
        "thresholds_triggered": [f"{risk_level.lower()}_threshold_violation"],
    }
