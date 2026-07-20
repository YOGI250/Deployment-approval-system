"""
test_audit_log.py

DEV-004: verifies the audit trail persists full ML + policy traceability
(confidence, model, model_version, policy_override, policy_reason,
triggered_policies).

Every test points audit_log at a throwaway sqlite-backed engine via the
`isolated_db` fixture below, so nothing here touches the real Neon
database.
"""

import os
import sys
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import audit_log


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Points audit_log at a fresh, empty sqlite-backed engine for one test."""
    db_path = str(tmp_path / "test_audit_log.db")
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(audit_log, "engine", test_engine)
    monkeypatch.setattr(audit_log, "SessionLocal", sessionmaker(bind=test_engine, autoflush=False, autocommit=False))
    return db_path


SAMPLE_DEPLOYMENT = {
    "deployment_id": "audit-test-001",
    "author": "meena",
    "team": "search",
    "files_changed": 3,
    "test_coverage_pct": 95.0,
    "environment": "staging",
    "failed_at_stage": None,
    "pipeline_stage_success_ratio": 0.9,
}

SAMPLE_RESULT_NO_OVERRIDE = {
    "risk_level": "Low",
    "confidence": 0.82,
    "reasoning": "Small, well-tested change.",
    "suggested_action": "None needed",
    "model": "RandomForest",
    "model_version": "1.0",
    "prompt_version": "v4.0-policy-engine-integrated",
    "degraded": False,
    "policy_override": False,
    "policy_reason": None,
    "triggered_policies": [],
}

SAMPLE_RESULT_WITH_OVERRIDE = {
    "risk_level": "High",
    "confidence": 0.67,
    "reasoning": "Coverage below the production minimum triggered an override.",
    "suggested_action": "Increase test coverage before redeploying.",
    "model": "RandomForest",
    "model_version": "1.0",
    "prompt_version": "v4.0-policy-engine-integrated",
    "degraded": False,
    "policy_override": True,
    "policy_reason": "Production deployment with test coverage 20.0% below the required minimum of 50%",
    "triggered_policies": ["rule_1_production_min_coverage"],
}


class TestAuditInsertionAndRetrieval:
    def test_insert_and_retrieve_round_trips_all_fields(self, isolated_db):
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")

        rows = audit_log.get_all_logs()
        assert len(rows) == 1
        row = rows[0]

        assert row["deployment_id"] == "audit-test-001"
        assert row["risk_level"] == "Low"
        assert row["decision"] == "approve"
        assert row["reasoning"] == SAMPLE_RESULT_NO_OVERRIDE["reasoning"]
        assert row["suggested_action"] == SAMPLE_RESULT_NO_OVERRIDE["suggested_action"]
        # new DEV-004 fields
        assert row["confidence"] == 0.82
        assert row["model"] == "RandomForest"
        assert row["model_version"] == "1.0"
        assert row["prompt_version"] == "v4.0-policy-engine-integrated"

    def test_multiple_rows_ordered_newest_first(self, isolated_db):
        audit_log.init_db()
        audit_log.log_decision({**SAMPLE_DEPLOYMENT, "deployment_id": "first"}, SAMPLE_RESULT_NO_OVERRIDE, "approve")
        audit_log.log_decision({**SAMPLE_DEPLOYMENT, "deployment_id": "second"}, SAMPLE_RESULT_NO_OVERRIDE, "approve")

        rows = audit_log.get_all_logs()
        assert len(rows) == 2
        assert rows[0]["deployment_id"] == "second"  # newest first
        assert rows[1]["deployment_id"] == "first"


class TestNoOverridePersistence:
    def test_no_override_defaults_are_falsy_and_empty_list(self, isolated_db):
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["policy_override"] == 0
        assert row["policy_reason"] is None
        assert row["triggered_policies"] == []  # decoded from JSON, not the string "[]"

    def test_result_missing_policy_keys_entirely_does_not_crash(self, isolated_db):
        """Older-shaped result dicts (pre-DEV-003) must still insert safely."""
        audit_log.init_db()
        minimal_result = {
            "risk_level": "Low", "reasoning": "ok", "suggested_action": "None needed",
            "prompt_version": "v3.0-ml-driven-explanation-only", "degraded": False,
        }
        audit_log.log_decision(SAMPLE_DEPLOYMENT, minimal_result, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["policy_override"] == 0
        assert row["policy_reason"] is None
        assert row["triggered_policies"] == []
        assert row["confidence"] is None
        assert row["model"] is None


class TestPolicyOverridePersistence:
    def test_override_fields_persist_and_triggered_policies_is_a_real_list(self, isolated_db):
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_WITH_OVERRIDE, decision="reject")

        row = audit_log.get_all_logs()[0]
        assert row["policy_override"] == 1
        assert row["policy_reason"] == SAMPLE_RESULT_WITH_OVERRIDE["policy_reason"]
        assert row["triggered_policies"] == ["rule_1_production_min_coverage"]
        assert isinstance(row["triggered_policies"], list)  # not a comma-separated string

    def test_multiple_triggered_policies_round_trip_in_order(self, isolated_db):
        audit_log.init_db()
        multi_policy_result = {
            **SAMPLE_RESULT_WITH_OVERRIDE,
            "triggered_policies": ["rule_2_global_max_failed_tests", "rule_4_production_critical_file_with_failures"],
        }
        audit_log.log_decision(SAMPLE_DEPLOYMENT, multi_policy_result, decision="reject")

        row = audit_log.get_all_logs()[0]
        assert row["triggered_policies"] == [
            "rule_2_global_max_failed_tests",
            "rule_4_production_critical_file_with_failures",
        ]


class TestTrainingFieldsPersistence:
    """DEV-011: lines_changed/tests_failed/changed_files/day_of_week/hour
    -- added so audit-log rows carry everything build_features() needs,
    letting train_model.py blend real outcomes into training data."""

    def test_new_fields_round_trip(self, isolated_db):
        audit_log.init_db()
        deployment = {
            **SAMPLE_DEPLOYMENT,
            "lines_changed": 340,
            "tests_failed": 1,
            "changed_files": ["app/payment_gateway.py", "app/utils.py"],
            "day_of_week": "Fri",
            "hour": 18,
        }
        audit_log.log_decision(deployment, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["lines_changed"] == 340
        assert row["tests_failed"] == 1
        assert row["changed_files"] == ["app/payment_gateway.py", "app/utils.py"]
        assert isinstance(row["changed_files"], list)  # decoded from JSON, not the raw string
        assert row["day_of_week"] == "Fri"
        assert row["hour"] == 18

    def test_missing_new_fields_default_to_none_or_empty_list(self, isolated_db):
        """SAMPLE_DEPLOYMENT predates these fields -- must not crash."""
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["lines_changed"] is None
        assert row["tests_failed"] is None
        assert row["changed_files"] == []
        assert row["day_of_week"] is None
        assert row["hour"] is None


class TestThresholdFieldsPersistence:
    """DEV-012: threshold_override/threshold_reason/triggered_thresholds
    -- added so threshold_engine.py's escalation decisions are just as
    auditable as policy_engine's overrides, mirroring
    TestPolicyOverridePersistence/TestNoOverridePersistence above."""

    def test_no_threshold_override_defaults_are_falsy_and_empty_list(self, isolated_db):
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["threshold_override"] == 0
        assert row["threshold_reason"] is None
        assert row["triggered_thresholds"] == []  # decoded from JSON, not the string "[]"

    def test_threshold_override_fields_persist_and_triggered_thresholds_is_a_real_list(self, isolated_db):
        audit_log.init_db()
        result = {
            **SAMPLE_RESULT_NO_OVERRIDE,
            "risk_level": "Medium",
            "threshold_override": True,
            "threshold_reason": "Deployment landed in Low but doesn't meet the current Low threshold bar: test coverage 50% is below this tier's minimum of 85%",
            "triggered_thresholds": ["low_threshold_violation"],
        }
        audit_log.log_decision(SAMPLE_DEPLOYMENT, result, decision="delay")

        row = audit_log.get_all_logs()[0]
        assert row["threshold_override"] == 1
        assert row["threshold_reason"] == result["threshold_reason"]
        assert row["triggered_thresholds"] == ["low_threshold_violation"]
        assert isinstance(row["triggered_thresholds"], list)  # not a comma-separated string

    def test_result_missing_threshold_keys_entirely_does_not_crash(self, isolated_db):
        """Older-shaped result dicts (pre-DEV-012) must still insert safely."""
        audit_log.init_db()
        minimal_result = {
            "risk_level": "Low", "reasoning": "ok", "suggested_action": "None needed",
            "prompt_version": "v4.0-policy-engine-integrated", "degraded": False,
        }
        audit_log.log_decision(SAMPLE_DEPLOYMENT, minimal_result, decision="approve")

        row = audit_log.get_all_logs()[0]
        assert row["threshold_override"] == 0
        assert row["threshold_reason"] is None
        assert row["triggered_thresholds"] == []


class TestInitDbIdempotency:
    def test_init_db_is_idempotent(self, isolated_db):
        """Calling init_db() repeatedly (every API startup) must not error or duplicate columns."""
        audit_log.init_db()
        audit_log.init_db()
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")
        assert len(audit_log.get_all_logs()) == 1
