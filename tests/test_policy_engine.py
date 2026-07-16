"""
test_policy_engine.py

DEV-003: unit tests for the deterministic policy layer (app/policy_engine.py)
plus two integration tests proving risk_scorer.score_deployment() actually
wires policy_engine in between the ML predictor and the decision engine.

Unit tests pass an explicit `policy` dict into evaluate_policies() rather
than relying on data/deployment_policy.json, so they stay stable even if
the shipped config's threshold values are tuned later -- what's under test
is the RULE LOGIC, not today's specific numbers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("GROQ_API_KEY", "test-key-for-non-network-tests")

from policy_engine import evaluate_policies, load_policy

TEST_POLICY = {
    "global": {"maximum_failed_tests": 0, "critical_file_coverage_threshold": 60},
    "production": {
        "minimum_test_coverage": 50,
        "friday_evening_escalation": True,
        "friday_evening_start_hour": 18,
        "critical_files_require_high": True,
    },
    "development": {},
    "staging": {},
}


def clean_deployment(**overrides):
    base = {
        "environment": "staging",
        "test_coverage_pct": 90,
        "tests_failed": 0,
        "changed_files": ["app/readme_updater.py"],
        "day_of_week": "Tue",
        "hour": 11,
    }
    base.update(overrides)
    return base


class TestNoOverride:
    def test_clean_deployment_keeps_ml_prediction(self):
        result = evaluate_policies(clean_deployment(), {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "Low"
        assert result["overridden"] is False
        assert result["override_reason"] is None
        assert result["policy_triggered"] == []

    def test_clean_production_deployment_keeps_ml_prediction(self):
        deployment = clean_deployment(environment="production", test_coverage_pct=95, day_of_week="Wed", hour=10)
        result = evaluate_policies(deployment, {"risk_level": "Medium"}, policy=TEST_POLICY)
        assert result["risk_level"] == "Medium"
        assert result["overridden"] is False
        assert result["policy_triggered"] == []


class TestRule1CoverageOverride:
    def test_production_low_coverage_overrides_to_high(self):
        deployment = clean_deployment(environment="production", test_coverage_pct=30)
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "High"
        assert result["overridden"] is True
        assert "rule_1_production_min_coverage" in result["policy_triggered"]
        assert "30" in result["override_reason"]

    def test_non_production_low_coverage_does_not_trigger_rule_1(self):
        deployment = clean_deployment(environment="staging", test_coverage_pct=10)
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert "rule_1_production_min_coverage" not in result["policy_triggered"]


class TestRule2FailedTestsOverride:
    def test_failed_test_overrides_to_high_in_any_environment(self):
        for env in ("staging", "development", "production"):
            deployment = clean_deployment(environment=env, tests_failed=1)
            result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
            assert result["risk_level"] == "High", f"expected High for env={env}"
            assert "rule_2_global_max_failed_tests" in result["policy_triggered"]
            assert result["overridden"] is True


class TestRule3CriticalFileCoverageOverride:
    def test_critical_file_with_low_coverage_overrides_to_high_anywhere(self):
        deployment = clean_deployment(
            environment="development",
            changed_files=["app/payment_gateway.py"],
            test_coverage_pct=55,
        )
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "High"
        assert "rule_3_global_critical_file_coverage" in result["policy_triggered"]

    def test_critical_file_with_adequate_coverage_does_not_trigger_rule_3(self):
        deployment = clean_deployment(
            environment="development",
            changed_files=["app/payment_gateway.py"],
            test_coverage_pct=75,
        )
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert "rule_3_global_critical_file_coverage" not in result["policy_triggered"]


class TestRule4ProductionCriticalFileWithFailure:
    def test_production_critical_file_and_failed_test_overrides_to_high(self):
        deployment = clean_deployment(
            environment="production",
            changed_files=["app/auth/login.py"],
            tests_failed=1,
            test_coverage_pct=95,  # deliberately high, so rule 1/3 don't also fire
        )
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "High"
        assert "rule_4_production_critical_file_with_failures" in result["policy_triggered"]

    def test_non_production_critical_file_and_failed_test_does_not_trigger_rule_4(self):
        deployment = clean_deployment(
            environment="staging",
            changed_files=["app/auth/login.py"],
            tests_failed=1,
            test_coverage_pct=95,
        )
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert "rule_4_production_critical_file_with_failures" not in result["policy_triggered"]
        # rule 2 (global, any failed test) still fires independently
        assert "rule_2_global_max_failed_tests" in result["policy_triggered"]


class TestRule5FridayEveningEscalation:
    def test_friday_evening_production_escalates_low_to_medium(self):
        deployment = clean_deployment(environment="production", day_of_week="Fri", hour=19, test_coverage_pct=95)
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "Medium"
        assert result["overridden"] is True
        assert "rule_5_production_friday_evening_escalation" in result["policy_triggered"]

    def test_friday_evening_production_escalates_medium_to_high(self):
        deployment = clean_deployment(environment="production", day_of_week="Fri", hour=20, test_coverage_pct=95)
        result = evaluate_policies(deployment, {"risk_level": "Medium"}, policy=TEST_POLICY)
        assert result["risk_level"] == "High"
        assert result["overridden"] is True

    def test_friday_evening_production_high_stays_high_but_still_flagged(self):
        deployment = clean_deployment(environment="production", day_of_week="Fri", hour=22, test_coverage_pct=95)
        result = evaluate_policies(deployment, {"risk_level": "High"}, policy=TEST_POLICY)
        assert result["risk_level"] == "High"
        assert result["overridden"] is False  # nothing actually changed vs. the ML prediction
        assert "rule_5_production_friday_evening_escalation" in result["policy_triggered"]  # but the policy did match

    def test_friday_before_evening_hour_does_not_escalate(self):
        deployment = clean_deployment(environment="production", day_of_week="Fri", hour=14, test_coverage_pct=95)
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "Low"
        assert "rule_5_production_friday_evening_escalation" not in result["policy_triggered"]

    def test_thursday_evening_does_not_escalate(self):
        deployment = clean_deployment(environment="production", day_of_week="Thu", hour=22, test_coverage_pct=95)
        result = evaluate_policies(deployment, {"risk_level": "Low"}, policy=TEST_POLICY)
        assert result["risk_level"] == "Low"
        assert "rule_5_production_friday_evening_escalation" not in result["policy_triggered"]


class TestPolicyConfigLoads:
    def test_shipped_policy_file_loads_and_has_expected_sections(self):
        policy = load_policy()
        assert "global" in policy
        assert "production" in policy
        assert "maximum_failed_tests" in policy["global"]
        assert "minimum_test_coverage" in policy["production"]


class TestFullPipelineIntegration:
    """Proves risk_scorer.score_deployment() actually calls policy_engine
    between the ML predictor and the decision engine, end to end."""

    def test_overridden_deployment_reflects_policy_in_final_response(self):
        import risk_scorer

        deployment = {
            "author": "sanjay", "team": "payments", "files_changed": 10, "lines_changed": 200,
            "test_coverage_pct": 20.0, "tests_failed": 0, "environment": "production",
            "day_of_week": "Wed", "hour": 10, "changed_files": ["app/notes.md"],
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)

        assert result["risk_level"] == "High"  # rule 1: production + coverage 20% < 50%
        assert result["policy_override"] is True
        assert "rule_1_production_min_coverage" in result["triggered_policies"]
        assert result["policy_reason"]
        assert result["decision"] == "reject"  # decision_engine sees the FINAL (post-policy) risk
        assert result["reasoning"]  # Groq still produces an explanation

    def test_clean_deployment_is_not_overridden(self):
        import risk_scorer

        deployment = {
            "author": "meena", "team": "search", "files_changed": 3, "lines_changed": 40,
            "test_coverage_pct": 95.0, "tests_failed": 0, "environment": "staging",
            "day_of_week": "Tue", "hour": 11, "changed_files": ["app/search_index.py"],
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)

        assert result["policy_override"] is False
        assert result["policy_reason"] is None
        assert result["triggered_policies"] == []
        assert result["risk_level"] in ("Low", "Medium", "High")  # whatever the ML model said, untouched


if __name__ == "__main__":
    import risk_scorer

    print("\n=== Example OVERRIDDEN deployment (production, low coverage) ===")
    overridden_deployment = {
        "author": "sanjay", "team": "payments", "files_changed": 10, "lines_changed": 200,
        "test_coverage_pct": 20.0, "tests_failed": 0, "environment": "production",
        "day_of_week": "Wed", "hour": 10, "changed_files": ["app/notes.md"],
    }
    print("Input:", overridden_deployment)
    print("Response:", risk_scorer.score_deployment(overridden_deployment))

    print("\n=== Example NON-OVERRIDDEN deployment (clean staging deploy) ===")
    clean_dep = {
        "author": "meena", "team": "search", "files_changed": 3, "lines_changed": 40,
        "test_coverage_pct": 95.0, "tests_failed": 0, "environment": "staging",
        "day_of_week": "Tue", "hour": 11, "changed_files": ["app/search_index.py"],
    }
    print("Input:", clean_dep)
    print("Response:", risk_scorer.score_deployment(clean_dep))
