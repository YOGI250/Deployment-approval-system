"""
test_deployment_verification.py

DEV-009: verifies GET /health and POST /deployment-verification --
enterprise deployment verification. Every test points audit_log at a
throwaway sqlite file via the `isolated_db` fixture (same pattern as
test_audit_log.py), so nothing here touches the real data/audit_log.db,
and none of it requires a live Groq call or a real deployed service.
"""

import os
import sys
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["API_KEY"] = "test-secret-123"

import pytest
from fastapi.testclient import TestClient

import audit_log
import api
importlib.reload(api)  # picks up API_KEY set above, same as test_api_auth.py

client = TestClient(api.app)

HEADERS = {"X-API-Key": "test-secret-123"}

SAMPLE_DEPLOYMENT = {
    "deployment_id": "verify-test-001",
    "author": "meena",
    "team": "search",
    "files_changed": 3,
    "test_coverage_pct": 95.0,
    "environment": "production",
    "failed_at_stage": None,
    "pipeline_stage_success_ratio": 0.9,
}

SAMPLE_RESULT = {
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


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """Points audit_log (and api.py's imported references to it) at a fresh sqlite file for one test."""
    db_path = str(tmp_path / "test_audit_log.db")
    monkeypatch.setattr(audit_log, "DB_FILE", db_path)
    audit_log.init_db()
    return db_path


class TestHealthEndpoint:
    def test_health_does_not_require_auth(self, isolated_db):
        response = client.get("/health")
        assert response.status_code in (200, 503)  # reachable without X-API-Key either way

    def test_health_returns_expected_shape(self, isolated_db):
        response = client.get("/health")
        body = response.json()
        for key in ("status", "model", "version", "database", "timestamp"):
            assert key in body

    def test_health_healthy_when_model_and_db_ok(self, isolated_db, monkeypatch):
        monkeypatch.setattr(api, "_get_model", lambda: object())
        monkeypatch.setattr(api, "check_connection", lambda: True)

        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["model"] == "RandomForest"
        assert body["version"] == "1.0"
        assert body["database"] == "connected"

    def test_health_unhealthy_and_503_when_model_fails_to_load(self, isolated_db, monkeypatch):
        def _raise():
            raise FileNotFoundError("no model")
        monkeypatch.setattr(api, "_get_model", _raise)
        monkeypatch.setattr(api, "check_connection", lambda: True)

        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert body["model"] == "unavailable"
        assert body["version"] is None

    def test_health_unhealthy_and_503_when_database_unreachable(self, isolated_db, monkeypatch):
        monkeypatch.setattr(api, "_get_model", lambda: object())
        monkeypatch.setattr(api, "check_connection", lambda: False)

        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert body["database"] == "unreachable"


class TestDeploymentVerificationEndpoint:
    def test_requires_auth(self, isolated_db):
        response = client.post("/deployment-verification", json={
            "deployment_id": "verify-test-001",
            "health_status": "healthy",
            "http_status_code": 200,
        })
        assert response.status_code == 401

    def test_healthy_check_marks_success_and_updates_audit_log(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "verify-test-001",
                "health_status": "healthy",
                "http_status_code": 200,
                "health_check": {"status": "healthy", "model": "RandomForest", "version": "1.0",
                                  "database": "connected", "timestamp": "2026-07-16T00:00:00+00:00"},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["deployment_status"] == "success"

        row = audit_log.get_all_logs()[0]
        assert row["deployment_id"] == "verify-test-001"
        assert row["deployment_status"] == "success"
        assert row["health_check"]["status"] == "healthy"
        assert row["verification_time"]
        # existing fields from the original decision must be untouched
        assert row["risk_level"] == "Low"
        assert row["decision"] == "approve"

    def test_non_200_marks_failed(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "verify-test-001",
                "health_status": "unhealthy",
                "http_status_code": 503,
                "health_check": {"status": "unhealthy", "database": "unreachable"},
            },
        )
        assert response.status_code == 200
        assert response.json()["deployment_status"] == "failed"

        row = audit_log.get_all_logs()[0]
        assert row["deployment_status"] == "failed"

    def test_unknown_deployment_id_does_not_crash(self, isolated_db):
        """No matching audit log row -- must not raise, just no-op the update."""
        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "does-not-exist",
                "health_status": "healthy",
                "http_status_code": 200,
            },
        )
        assert response.status_code == 200

    def test_health_check_field_is_optional(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "verify-test-001",
                "health_status": "unhealthy",
                "http_status_code": 0,
            },
        )
        assert response.status_code == 200
        row = audit_log.get_all_logs()[0]
        assert row["health_check"] is None


class TestBackwardCompatibility:
    """DEV-009 must not disturb existing endpoints or the audit log schema."""

    def test_predict_endpoint_still_present(self):
        assert any(route.path == "/predict" for route in api.app.routes)

    def test_root_health_check_unchanged(self, isolated_db):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "message": "Deployment Risk Assistant is running"}

    def test_old_shaped_row_without_verification_fields_still_reads_fine(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")
        row = audit_log.get_all_logs()[0]
        assert row["deployment_status"] is None
        assert row["health_check"] is None
        assert row["verification_time"] is None
