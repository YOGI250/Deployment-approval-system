"""
test_risk_scorer.py

Automated tests for the risk-scoring logic. Run with:
    pytest tests/ -v

These don't require a real Groq API key for most tests -- they test the
logic AROUND the AI call (file criticality, similarity search, prompt
building) which is where most real bugs tend to hide. The retry/fail-safe
test intentionally uses a bad key to prove the system degrades safely
instead of crashing, which matters for production reliability.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("GROQ_API_KEY", "test-key-for-non-network-tests")

from risk_scorer import (
    classify_file_criticality,
    find_similar_past_deployments,
    build_deployment_description,
    score_deployment,
)


class TestFileCriticality:
    def test_detects_payment_file(self):
        result = classify_file_criticality(["app/payment_processor.py"])
        assert result["has_critical_files"] is True
        assert "app/payment_processor.py" in result["matched_files"]

    def test_detects_auth_file(self):
        result = classify_file_criticality(["src/auth/login.py"])
        assert result["has_critical_files"] is True

    def test_ignores_docs_and_readme(self):
        result = classify_file_criticality(["README.md", "docs/guide.md"])
        assert result["has_critical_files"] is False
        assert result["matched_files"] == []

    def test_empty_list_does_not_crash(self):
        result = classify_file_criticality([])
        assert result["has_critical_files"] is False

    def test_mixed_files_only_flags_critical_ones(self):
        result = classify_file_criticality(["README.md", "config/secrets.yaml", "test_app.py"])
        assert result["has_critical_files"] is True
        assert "config/secrets.yaml" in result["matched_files"]
        assert "README.md" not in result["matched_files"]


class TestSimilarDeploymentRetrieval:
    def setup_method(self):
        self.history = [
            {"author": "alice", "files_changed": "10", "outcome": "success", "incident_severity": "none"},
            {"author": "bob", "files_changed": "80", "outcome": "fail", "incident_severity": "major"},
            {"author": "alice", "files_changed": "15", "outcome": "fail", "incident_severity": "minor"},
            {"author": "carol", "files_changed": "5", "outcome": "success", "incident_severity": "none"},
        ]

    def test_same_author_ranks_highest(self):
        deployment = {"author": "alice", "files_changed": "12"}
        results = find_similar_past_deployments(deployment, self.history)
        assert results[0]["author"] == "alice"
        assert results[1]["author"] == "alice"

    def test_empty_history_returns_empty(self):
        results = find_similar_past_deployments({"author": "alice", "files_changed": "5"}, [])
        assert results == []

    def test_respects_top_n(self):
        deployment = {"author": "alice", "files_changed": "12"}
        results = find_similar_past_deployments(deployment, self.history, top_n=2)
        assert len(results) == 2


class TestPromptBuilding:
    def test_flags_critical_files_in_description(self):
        deployment = {
            "author": "alice", "team": "payments", "files_changed": 5, "lines_changed": 100,
            "test_coverage_pct": 90, "tests_failed": 0, "environment": "production",
            "day_of_week": "Tue", "hour": 10, "changed_files": ["app/payment_processor.py"],
        }
        description = build_deployment_description(deployment)
        assert "YES" in description
        assert "payment_processor.py" in description

    def test_no_critical_files_shows_no(self):
        deployment = {
            "author": "alice", "team": "payments", "files_changed": 5, "lines_changed": 100,
            "test_coverage_pct": 90, "tests_failed": 0, "environment": "production",
            "day_of_week": "Tue", "hour": 10, "changed_files": ["README.md"],
        }
        description = build_deployment_description(deployment)
        assert "No" in description.split("critical files")[1].split("\n")[0]

    def test_includes_similar_history_when_provided(self):
        deployment = {
            "author": "alice", "team": "payments", "files_changed": 5, "lines_changed": 100,
            "test_coverage_pct": 90, "tests_failed": 0, "environment": "production",
            "day_of_week": "Tue", "hour": 10,
        }
        history = [{"author": "alice", "files_changed": "6", "outcome": "fail", "incident_severity": "minor"}]
        description = build_deployment_description(deployment, history)
        assert "Most similar past deployments" in description
        assert "fail" in description


class TestDynamicThresholds:
    def test_thresholds_load_from_file(self):
        from risk_scorer import load_thresholds
        thresholds = load_thresholds()
        assert "low" in thresholds
        assert "medium" in thresholds
        assert "max_files_changed" in thresholds["low"]

    def test_prompt_reflects_current_thresholds(self):
        from risk_scorer import build_system_prompt
        thresholds = {
            "low": {"max_files_changed": 99, "min_test_coverage_pct": 77, "max_tests_failed": 0, "min_author_success_rate": 0.85},
            "medium": {"max_files_changed": 150, "min_test_coverage_pct": 50, "max_tests_failed": 1, "min_author_success_rate": 0.7},
        }
        prompt = build_system_prompt(thresholds)
        assert "99" in prompt
        assert "77" in prompt

    def test_adjust_thresholds_tightens_low_on_high_failure_rate(self):
        from adjust_thresholds import adjust_thresholds
        fail_rates = {
            "Low": {"fail_rate": 0.25, "sample_size": 12},
            "Medium": {"fail_rate": None, "sample_size": 0},
            "High": {"fail_rate": None, "sample_size": 0},
        }
        thresholds = {
            "low": {"max_files_changed": 20, "min_test_coverage_pct": 80, "max_tests_failed": 0, "min_author_success_rate": 0.85},
            "medium": {"max_files_changed": 50, "min_test_coverage_pct": 60, "max_tests_failed": 1, "min_author_success_rate": 0.7},
        }
        updated, reason = adjust_thresholds(fail_rates, thresholds)
        assert reason is not None
        assert updated["low"]["min_test_coverage_pct"] > 80  # got stricter

    def test_adjust_thresholds_leaves_alone_with_small_sample(self):
        from adjust_thresholds import adjust_thresholds
        fail_rates = {
            "Low": {"fail_rate": 0.50, "sample_size": 3},  # high fail rate but too few samples
            "Medium": {"fail_rate": None, "sample_size": 0},
            "High": {"fail_rate": None, "sample_size": 0},
        }
        thresholds = {
            "low": {"max_files_changed": 20, "min_test_coverage_pct": 80, "max_tests_failed": 0, "min_author_success_rate": 0.85},
            "medium": {"max_files_changed": 50, "min_test_coverage_pct": 60, "max_tests_failed": 1, "min_author_success_rate": 0.7},
        }
        updated, reason = adjust_thresholds(fail_rates, thresholds)
        assert reason is None  # should NOT adjust based on 3 samples
        assert updated["low"]["min_test_coverage_pct"] == 80  # unchanged


class TestFailSafeRetry:
    def test_bad_api_key_fails_safe_not_crash(self):
        """
        This is a critical production-reliability test: if Groq (the
        explanation service) is unreachable, the whole deployment
        pipeline should NOT crash. Since DEV-002, Groq no longer
        determines risk_level -- the ML model does, and it doesn't call
        out to any network service, so it's unaffected by Groq being
        down. Only reasoning/suggested_action should degrade to a safe
        placeholder; risk_level must still be a real ML-predicted value,
        not a hardcoded fallback.
        """
        os.environ["GROQ_API_KEY"] = "definitely-invalid-key"
        import importlib
        import risk_scorer
        importlib.reload(risk_scorer)

        deployment = {
            "author": "alice", "team": "payments", "files_changed": 5, "lines_changed": 100,
            "test_coverage_pct": 90, "tests_failed": 0, "environment": "production",
            "day_of_week": "Tue", "hour": 10,
        }
        result = risk_scorer.score_deployment(deployment, max_retries=1)
        assert result["risk_level"] in ("Low", "Medium", "High")  # from the ML model, unaffected by Groq being down
        assert result["decision"] in ("approve", "delay", "reject")
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["degraded"] is True  # the explanation, not the risk judgment, degraded
        assert "AI explanation service was unreachable" in result["reasoning"]
        assert "prompt_version" in result
