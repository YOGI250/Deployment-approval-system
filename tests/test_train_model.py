"""
test_train_model.py

DEV-011: verifies train_model.py blends real, outcome-verified audit-log
rows into training data alongside the synthetic CSV baseline, and that
the DB-unavailable path degrades gracefully (falls back to CSV-only)
instead of crashing -- required so `python3 train_model.py` still works
standalone in local dev / CI without DB secrets.

audit_log.py is faked via sys.modules rather than imported for real,
since train_model.py's load_real_audit_rows() does a deferred
`import audit_log` precisely so a missing/unreachable database doesn't
break module import -- these tests exercise that same seam.
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "ml"))

import train_model


def _fake_audit_log(get_all_logs):
    module = types.ModuleType("audit_log")
    module.get_all_logs = get_all_logs
    return module


class TestLoadRealAuditRows:
    def test_filters_to_rows_with_known_outcome(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "audit_log", _fake_audit_log(lambda: [
            {"deployment_id": "a", "actual_outcome": "success"},
            {"deployment_id": "b", "actual_outcome": None},
            {"deployment_id": "c", "actual_outcome": "fail"},
        ]))

        rows = train_model.load_real_audit_rows()
        assert [r["deployment_id"] for r in rows] == ["a", "c"]

    def test_db_unavailable_returns_empty_list_not_a_crash(self, monkeypatch):
        def _raise():
            raise RuntimeError("DATABASE_URL is not set")
        monkeypatch.setitem(sys.modules, "audit_log", _fake_audit_log(_raise))

        assert train_model.load_real_audit_rows() == []


class TestDeriveRiskLabel:
    def test_success_is_low(self):
        assert train_model.derive_risk_label({"outcome": "success"}) == "Low"

    def test_fail_major_is_high(self):
        assert train_model.derive_risk_label({"outcome": "fail", "incident_severity": "major"}) == "High"

    def test_fail_minor_is_medium(self):
        assert train_model.derive_risk_label({"outcome": "fail", "incident_severity": "minor"}) == "Medium"


class TestLoadTrainingDataBlending:
    REAL_ROW = {
        "deployment_id": "real-1", "author": "chandana", "team": "payments",
        "files_changed": 4, "lines_changed": 120, "test_coverage_pct": 88.0,
        "tests_failed": 0, "changed_files": ["app/api.py"], "day_of_week": "Tue",
        "hour": 10, "environment": "production", "pipeline_stage_success_ratio": 1.0,
        "actual_outcome": "success", "incident_severity": "none",
    }

    def test_real_rows_are_blended_with_csv_rows(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "audit_log", _fake_audit_log(lambda: [self.REAL_ROW]))

        X, y, n_csv, n_real = train_model.load_training_data()
        assert n_real == 1
        assert n_csv == 500  # the 500-row starter history this repo always ships
        assert len(X) == len(y) == n_csv + n_real
        assert y[-1] == "Low"  # the injected real row: success, no incident

    def test_unverified_real_rows_are_excluded_from_blend(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "audit_log", _fake_audit_log(lambda: [
            {**self.REAL_ROW, "actual_outcome": None},
        ]))

        X, y, n_csv, n_real = train_model.load_training_data()
        assert n_real == 0
        assert len(X) == n_csv

    def test_no_database_falls_back_to_csv_only(self, monkeypatch):
        def _raise():
            raise RuntimeError("DATABASE_URL is not set")
        monkeypatch.setitem(sys.modules, "audit_log", _fake_audit_log(_raise))

        X, y, n_csv, n_real = train_model.load_training_data()
        assert n_real == 0
        assert len(X) == n_csv == 500
