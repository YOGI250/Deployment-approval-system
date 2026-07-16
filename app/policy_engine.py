"""
policy_engine.py

Deterministic governance layer that sits between the ML predictor and the
decision engine. Enterprise safety policies take precedence over the
statistical prediction: if a deployment trips a mandatory rule (production
deployment with failing tests, critical files changed with weak coverage,
a late Friday production push, etc.), risk is overridden regardless of
what the Random Forest model predicted.

Never calls Groq. Never calls FastAPI. Takes a deployment dict and the
ML prediction dict, returns a plain decision -- nothing here reaches out
to any other part of the system.

All thresholds are loaded from data/deployment_policy.json; no coverage
percentage, failed-test count, or hour cutoff is hardcoded below -- only
the five rule *conditions* themselves (which are the deterministic
governance logic this module exists to own) are Python.
"""

import os
import json
import logging

logger = logging.getLogger("policy_engine")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
POLICY_PATH = os.path.join(DATA_DIR, "deployment_policy.json")

RISK_LEVELS = ["Low", "Medium", "High"]

# Used only if deployment_policy.json is missing -- mirrors the file's
# shipped defaults so the system still fails toward caution rather than
# skipping policy checks entirely.
DEFAULT_POLICY = {
    "global": {"maximum_failed_tests": 0, "critical_file_coverage_threshold": 60},
    "production": {
        "minimum_test_coverage": 50,
        "friday_evening_escalation": True,
        "friday_evening_start_hour": 18,
        "critical_files_require_high": True,
    },
}

# Duplicated from feature_engineering.py / risk_scorer.py deliberately --
# same reasoning as feature_engineering.py's own copy: this module must
# stay independently runnable/testable without importing the rest of the
# app.
CRITICAL_FILE_PATTERNS = [
    "payment", "billing", "auth", "login", "security", "credential",
    "secret", ".env", "config", "migration", "schema",
]


def load_policy() -> dict:
    try:
        with open(POLICY_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("deployment_policy.json not found, using built-in defaults")
        return DEFAULT_POLICY


def _has_critical_files(changed_files) -> bool:
    if not changed_files:
        return False
    return any(
        any(pattern in f.lower() for pattern in CRITICAL_FILE_PATTERNS)
        for f in changed_files
    )


def _is_friday(day_of_week) -> bool:
    if not day_of_week:
        return False
    return str(day_of_week).strip().lower().startswith("fri")


def _escalate_one_level(risk_level: str) -> str:
    if risk_level not in RISK_LEVELS:
        return risk_level
    idx = RISK_LEVELS.index(risk_level)
    return RISK_LEVELS[min(idx + 1, len(RISK_LEVELS) - 1)]


def evaluate_policies(deployment: dict, ml_prediction: dict, policy: dict = None) -> dict:
    """
    Input:
        deployment: the raw deployment request dict (environment,
            test_coverage_pct, tests_failed, changed_files, day_of_week,
            hour, ...)
        ml_prediction: the ML predictor's output, at minimum
            {"risk_level": "Low"|"Medium"|"High"}

    Output:
        {
            "risk_level": "...",           # final risk after policy checks
            "overridden": True/False,      # final risk_level != ml_prediction's
            "override_reason": "..." | None,
            "policy_triggered": [...],     # every rule whose condition matched,
                                            # even ones that didn't change the value
        }

    Rules are evaluated in a fixed order (1 through 5) and are cumulative:
    each rule sees the risk level left behind by the rules before it, so a
    High set by an earlier rule stays High, and rule 5's "increase one
    level" escalates whatever level is current at that point. This keeps
    evaluation deterministic and every triggered condition auditable,
    whether or not it individually changed the outcome.
    """
    policy = policy or load_policy()
    global_policy = policy.get("global", {})
    environment = str(deployment.get("environment") or "").lower()
    env_policy = policy.get(environment, {})

    original_risk = ml_prediction["risk_level"]
    current_risk = original_risk
    triggered = []
    reasons = []

    try:
        test_coverage_pct = float(deployment.get("test_coverage_pct"))
    except (TypeError, ValueError):
        test_coverage_pct = None

    try:
        tests_failed = int(deployment.get("tests_failed", 0))
    except (TypeError, ValueError):
        tests_failed = 0

    has_critical_files = _has_critical_files(deployment.get("changed_files"))

    # Rule 1 (production only): coverage below the production minimum -> High
    minimum_test_coverage = env_policy.get("minimum_test_coverage")
    if (
        environment == "production"
        and minimum_test_coverage is not None
        and test_coverage_pct is not None
        and test_coverage_pct < minimum_test_coverage
    ):
        current_risk = "High"
        triggered.append("rule_1_production_min_coverage")
        reasons.append(
            f"Production deployment with test coverage {test_coverage_pct}% "
            f"below the required minimum of {minimum_test_coverage}%"
        )

    # Rule 2 (global): failed tests exceed the allowed maximum -> High
    maximum_failed_tests = global_policy.get("maximum_failed_tests")
    if maximum_failed_tests is not None and tests_failed > maximum_failed_tests:
        current_risk = "High"
        triggered.append("rule_2_global_max_failed_tests")
        reasons.append(
            f"{tests_failed} failed test(s) exceeds the maximum allowed ({maximum_failed_tests})"
        )

    # Rule 3 (global): critical files changed with weak coverage -> High
    critical_file_coverage_threshold = global_policy.get("critical_file_coverage_threshold")
    if (
        has_critical_files
        and critical_file_coverage_threshold is not None
        and test_coverage_pct is not None
        and test_coverage_pct < critical_file_coverage_threshold
    ):
        current_risk = "High"
        triggered.append("rule_3_global_critical_file_coverage")
        reasons.append(
            f"Critical files changed with test coverage {test_coverage_pct}% "
            f"below the required threshold of {critical_file_coverage_threshold}% for critical changes"
        )

    # Rule 4 (production only): critical files + any failing test -> High
    if (
        environment == "production"
        and env_policy.get("critical_files_require_high")
        and has_critical_files
        and tests_failed > 0
    ):
        current_risk = "High"
        triggered.append("rule_4_production_critical_file_with_failures")
        reasons.append(
            "Production deployment with critical files changed and failing tests"
        )

    # Rule 5 (production only): Friday at/after the configured evening hour
    # escalates risk one level (Low->Medium, Medium->High, High stays High)
    if environment == "production" and env_policy.get("friday_evening_escalation"):
        start_hour = env_policy.get("friday_evening_start_hour", 18)
        hour = deployment.get("hour")
        if _is_friday(deployment.get("day_of_week")) and hour is not None and hour >= start_hour:
            pre_escalation_risk = current_risk
            current_risk = _escalate_one_level(current_risk)
            triggered.append("rule_5_production_friday_evening_escalation")
            reasons.append(
                f"Production deployment on Friday at/after {start_hour}:00 "
                f"escalates risk one level (was {pre_escalation_risk})"
            )

    return {
        "risk_level": current_risk,
        "overridden": current_risk != original_risk,
        "override_reason": " ; ".join(reasons) if reasons else None,
        "policy_triggered": triggered,
    }
