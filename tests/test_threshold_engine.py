"""
test_threshold_engine.py

Unit tests for the deterministic threshold-calibration layer
(app/threshold_engine.py) plus integration tests proving
risk_scorer.score_deployment() actually wires it in between
policy_engine and decision_engine, so that data/risk_thresholds.json
(and adjust_thresholds.py, which rewrites it based on real audit-log
fail rates) has a real effect on the risk_level a deployment gets --
not just on the text Groq uses to explain it.

Unit tests pass an explicit thresholds dict into evaluate_thresholds()
rather than relying on data/risk_thresholds.json, so they stay stable
even if the shipped config's numbers are retuned later -- what's under
test is the ESCALATION LOGIC, not today's specific bar.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("GROQ_API_KEY", "test-key-for-non-network-tests")

from threshold_engine import evaluate_thresholds, _violations, _escalate_one_level

TEST_THRESHOLDS = {
    "low": {"max_files_changed": 15, "min_test_coverage_pct": 85, "max_tests_failed": 0, "min_author_success_rate": 0.85},
    "medium": {"max_files_changed": 50, "min_test_coverage_pct": 60, "max_tests_failed": 1, "min_author_success_rate": 0.7},
}


def clean_deployment(**overrides):
    base = {
        "files_changed": 5,
        "test_coverage_pct": 95,
        "tests_failed": 0,
        "author_recent_success_rate": 0.95,
    }
    base.update(overrides)
    return base


class TestEscalateOneLevel:
    def test_low_escalates_to_medium(self):
        assert _escalate_one_level("Low") == "Medium"

    def test_medium_escalates_to_high(self):
        assert _escalate_one_level("Medium") == "High"

    def test_high_stays_high(self):
        assert _escalate_one_level("High") == "High"

    def test_unknown_value_passes_through(self):
        assert _escalate_one_level("Unknown") == "Unknown"


class TestViolations:
    def test_clean_deployment_has_no_violations(self):
        assert _violations(clean_deployment(), TEST_THRESHOLDS["low"]) == []

    def test_too_many_files_changed_is_a_violation(self):
        reasons = _violations(clean_deployment(files_changed=20), TEST_THRESHOLDS["low"])
        assert len(reasons) == 1
        assert "files changed" in reasons[0]

    def test_low_coverage_is_a_violation(self):
        reasons = _violations(clean_deployment(test_coverage_pct=50), TEST_THRESHOLDS["low"])
        assert any("coverage" in r for r in reasons)

    def test_failed_tests_is_a_violation(self):
        reasons = _violations(clean_deployment(tests_failed=2), TEST_THRESHOLDS["low"])
        assert any("failed test" in r for r in reasons)

    def test_low_author_success_rate_is_a_violation(self):
        reasons = _violations(clean_deployment(author_recent_success_rate=0.5), TEST_THRESHOLDS["low"])
        assert any("success rate" in r for r in reasons)

    def test_multiple_violations_all_reported(self):
        reasons = _violations(
            clean_deployment(files_changed=100, test_coverage_pct=10, tests_failed=5, author_recent_success_rate=0.1),
            TEST_THRESHOLDS["low"],
        )
        assert len(reasons) == 4

    def test_missing_field_is_skipped_not_a_violation(self):
        deployment = {"files_changed": 5}  # no test_coverage_pct, tests_failed, or author_recent_success_rate
        assert _violations(deployment, TEST_THRESHOLDS["low"]) == []


class TestEvaluateThresholds:
    def test_clean_low_deployment_is_not_escalated(self):
        result = evaluate_thresholds(clean_deployment(), "Low", TEST_THRESHOLDS)
        assert result["risk_level"] == "Low"
        assert result["overridden"] is False
        assert result["override_reason"] is None
        assert result["thresholds_triggered"] == []

    def test_low_deployment_failing_low_bar_escalates_to_medium(self):
        deployment = clean_deployment(test_coverage_pct=50)  # meets Medium's 60% bar, fails Low's 85%
        result = evaluate_thresholds(deployment, "Low", TEST_THRESHOLDS)
        assert result["risk_level"] == "Medium"
        assert result["overridden"] is True
        assert "50" in result["override_reason"]
        assert result["thresholds_triggered"] == ["low_threshold_violation"]

    def test_medium_deployment_failing_medium_bar_escalates_to_high(self):
        deployment = clean_deployment(test_coverage_pct=10)  # below Medium's 60% bar too
        result = evaluate_thresholds(deployment, "Medium", TEST_THRESHOLDS)
        assert result["risk_level"] == "High"
        assert result["overridden"] is True
        assert result["thresholds_triggered"] == ["medium_threshold_violation"]

    def test_clean_medium_deployment_is_not_escalated(self):
        deployment = clean_deployment(files_changed=30, test_coverage_pct=65)  # meets Medium bar, fails Low bar
        result = evaluate_thresholds(deployment, "Medium", TEST_THRESHOLDS)
        assert result["overridden"] is False
        assert result["risk_level"] == "Medium"

    def test_high_never_escalates_no_bounds_defined(self):
        deployment = clean_deployment(files_changed=99999, test_coverage_pct=0, tests_failed=50)
        result = evaluate_thresholds(deployment, "High", TEST_THRESHOLDS)
        assert result["risk_level"] == "High"
        assert result["overridden"] is False
        assert result["thresholds_triggered"] == []


class TestFullPipelineIntegration:
    """Proves risk_scorer.score_deployment() actually calls
    threshold_engine after policy_engine and before decision_engine, and
    that its escalation reaches the final API response -- end to end."""

    def test_threshold_violation_escalates_final_risk_level(self, monkeypatch):
        import risk_scorer

        # Force a deterministic ML prediction of Low, and a fixed
        # thresholds config, so this test doesn't depend on the actual
        # model's behavior or today's shipped risk_thresholds.json values
        # -- only on threshold_engine actually being wired into the
        # pipeline and having a real effect on the final response.
        monkeypatch.setattr(risk_scorer, "ml_predict", lambda features: {
            "risk_level": "Low", "confidence": 0.9, "model": "RandomForest", "model_version": "1.0",
        })
        monkeypatch.setattr(risk_scorer, "load_thresholds", lambda: TEST_THRESHOLDS)

        deployment = {
            "author": "priya", "team": "checkout", "files_changed": 5, "lines_changed": 50,
            "test_coverage_pct": 40.0, "tests_failed": 0, "environment": "staging",
            "day_of_week": "Tue", "hour": 11, "changed_files": ["app/notes.md"],
            "author_recent_success_rate": 0.95,
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)

        assert result["risk_level"] == "Medium"  # escalated from the forced Low prediction
        assert result["threshold_override"] is True
        assert "low_threshold_violation" in result["triggered_thresholds"]
        assert result["threshold_reason"]
        assert result["decision"] == "delay"  # decision_engine sees the FINAL (post-threshold) risk

    def test_clean_deployment_is_not_threshold_overridden(self, monkeypatch):
        import risk_scorer

        monkeypatch.setattr(risk_scorer, "ml_predict", lambda features: {
            "risk_level": "Low", "confidence": 0.9, "model": "RandomForest", "model_version": "1.0",
        })
        monkeypatch.setattr(risk_scorer, "load_thresholds", lambda: TEST_THRESHOLDS)

        deployment = {
            "author": "meena", "team": "search", "files_changed": 3, "lines_changed": 40,
            "test_coverage_pct": 95.0, "tests_failed": 0, "environment": "staging",
            "day_of_week": "Tue", "hour": 11, "changed_files": ["app/search_index.py"],
            "author_recent_success_rate": 0.95,
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)

        assert result["risk_level"] == "Low"
        assert result["threshold_override"] is False
        assert result["threshold_reason"] is None
        assert result["triggered_thresholds"] == []

    def test_policy_override_takes_precedence_and_threshold_still_evaluated_after(self, monkeypatch):
        """A deployment that trips a mandatory policy rule (production +
        low coverage -> High) must land on High regardless of threshold
        calibration -- and since High has no bounds to check, it must
        NOT also show a threshold override, proving threshold_engine
        runs on the POST-policy risk level, not the raw ML one."""
        import risk_scorer

        monkeypatch.setattr(risk_scorer, "ml_predict", lambda features: {
            "risk_level": "Low", "confidence": 0.9, "model": "RandomForest", "model_version": "1.0",
        })
        monkeypatch.setattr(risk_scorer, "load_thresholds", lambda: TEST_THRESHOLDS)

        deployment = {
            "author": "sanjay", "team": "payments", "files_changed": 10, "lines_changed": 200,
            "test_coverage_pct": 20.0, "tests_failed": 0, "environment": "production",
            "day_of_week": "Wed", "hour": 10, "changed_files": ["app/notes.md"],
            "author_recent_success_rate": 0.95,
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)

        assert result["risk_level"] == "High"
        assert result["policy_override"] is True
        assert result["threshold_override"] is False  # High has no bounds -- nothing left to escalate
        assert result["triggered_thresholds"] == []
