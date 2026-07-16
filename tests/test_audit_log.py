"""
test_audit_log.py

DEV-004: verifies the audit trail persists full ML + policy traceability
(confidence, model, model_version, policy_override, policy_reason,
triggered_policies) and that an old, pre-DEV-004 database migrates
cleanly without requiring manual deletion.

Every test points audit_log.DB_FILE at a throwaway sqlite file via the
`isolated_db` fixture below, so nothing here touches the real
data/audit_log.db.
"""

import os
import sys
import json
import sqlite3

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import audit_log


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Points audit_log at a fresh, empty sqlite file for one test."""
    db_path = str(tmp_path / "test_audit_log.db")
    monkeypatch.setattr(audit_log, "DB_FILE", db_path)
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


class TestMigrationFromOldDatabase:
    def test_pre_dev004_database_migrates_without_manual_deletion(self, isolated_db):
        """
        Simulates a database created by the very first version of
        audit_log.py -- before prompt_version, degraded, and everything
        added since. init_db() must add the missing columns in place,
        and log_decision()/get_all_logs() must work immediately after,
        with no manual DB deletion or recreation required.
        """
        conn = sqlite3.connect(isolated_db)
        conn.execute("""
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deployment_id TEXT,
                author TEXT,
                team TEXT,
                files_changed INTEGER,
                test_coverage_pct REAL,
                environment TEXT,
                risk_level TEXT,
                reasoning TEXT,
                suggested_action TEXT,
                decision TEXT,
                actual_outcome TEXT,
                incident_severity TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO audit_log (
                deployment_id, author, team, files_changed, test_coverage_pct,
                environment, risk_level, reasoning, suggested_action, decision,
                actual_outcome, incident_severity, created_at
            ) VALUES ('legacy-001', 'alice', 'payments', 5, 90.0, 'production',
                      'Low', 'legacy row', 'None needed', 'approve', NULL, NULL,
                      '2025-01-01T00:00:00')
        """)
        conn.commit()
        conn.close()

        # This is the call every API startup makes -- must not raise, and
        # must not require deleting/recreating the file first.
        audit_log.init_db()

        conn = sqlite3.connect(isolated_db)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
        conn.close()
        for expected_column in (
            "prompt_version", "degraded", "failed_at_stage", "pipeline_stage_success_ratio",
            "confidence", "model", "model_version",
            "policy_override", "policy_reason", "triggered_policies",
        ):
            assert expected_column in columns, f"migration did not add {expected_column}"

        # the pre-existing legacy row must survive the migration untouched
        rows = audit_log.get_all_logs()
        assert len(rows) == 1
        assert rows[0]["deployment_id"] == "legacy-001"
        assert rows[0]["risk_level"] == "Low"
        assert rows[0]["confidence"] is None  # column didn't exist when this row was written
        assert rows[0]["triggered_policies"] == []  # NULL decodes to an empty list, not a crash

        # and new rows can be written immediately after migration
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_WITH_OVERRIDE, decision="reject")
        rows = audit_log.get_all_logs()
        assert len(rows) == 2

    def test_init_db_is_idempotent(self, isolated_db):
        """Calling init_db() repeatedly (every API startup) must not error or duplicate columns."""
        audit_log.init_db()
        audit_log.init_db()
        audit_log.init_db()
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT_NO_OVERRIDE, decision="approve")
        assert len(audit_log.get_all_logs()) == 1
