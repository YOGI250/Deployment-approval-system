"""
test_recovery_manager.py

DEV-010: verifies the Enterprise Deployment Recovery Framework --
recovery_manager.evaluate_recovery() directly, its persistence into the
audit log, its integration into POST /deployment-verification, the
recovery-required email, and that none of this disturbs existing
behavior. Every DB-touching test points audit_log at a throwaway sqlite
file via the `isolated_db` fixture, same pattern as
test_deployment_verification.py.
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
import recovery_manager
import email_notify
import api
importlib.reload(api)

client = TestClient(api.app)

HEADERS = {"X-API-Key": "test-secret-123"}

SAMPLE_DEPLOYMENT = {
    "deployment_id": "recovery-test-001",
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
    db_path = str(tmp_path / "test_audit_log.db")
    monkeypatch.setattr(audit_log, "DB_FILE", db_path)
    audit_log.init_db()
    return db_path


class TestEvaluateRecoveryHealthy:
    def test_healthy_deployment_needs_no_recovery(self):
        result = recovery_manager.evaluate_recovery(
            deployment_id="d-1", health_status="healthy", verification_time="2026-07-16T00:00:00+00:00"
        )
        assert result["deployment_status"] == "DEPLOYED"
        assert result["recovery_status"] == "NOT_REQUIRED"
        assert result["rollback_recommended"] is False
        assert result["timestamp"] == "2026-07-16T00:00:00+00:00"

    def test_healthy_result_shape(self):
        result = recovery_manager.evaluate_recovery("d-1", "healthy", "2026-07-16T00:00:00+00:00")
        for key in ("deployment_status", "recovery_status", "rollback_recommended",
                    "recovery_reason", "recommended_action", "timestamp"):
            assert key in result


class TestEvaluateRecoveryFailed:
    def test_failed_deployment_requires_recovery(self):
        result = recovery_manager.evaluate_recovery(
            deployment_id="d-2", health_status="unhealthy", verification_time="2026-07-16T00:05:00+00:00"
        )
        assert result["deployment_status"] == "FAILED"
        assert result["recovery_status"] == "RECOVERY_REQUIRED"
        assert result["rollback_recommended"] is True
        assert result["recovery_reason"]
        assert result["recommended_action"] == (
            "Rollback to previous stable deployment or redeploy after fixing the issue."
        )
        assert result["timestamp"] == "2026-07-16T00:05:00+00:00"

    def test_no_azure_rollback_language_or_action_is_ever_claimed(self):
        """The ticket is explicit: no fake rollback claims. Nothing in the
        result should assert that Azure itself was reverted."""
        result = recovery_manager.evaluate_recovery("d-2", "unhealthy", "2026-07-16T00:05:00+00:00")
        combined = " ".join(str(v) for v in result.values()).lower()
        assert "reverted" not in combined
        assert "rolled back automatically" not in combined


class TestAuditPersistence:
    def test_update_recovery_persists_all_four_fields(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        rows_updated = audit_log.update_recovery(
            deployment_id="recovery-test-001",
            recovery_status="RECOVERY_REQUIRED",
            rollback_recommended=True,
            recovery_reason="Post-deployment health check failed.",
            recovery_timestamp="2026-07-16T00:05:00+00:00",
        )
        assert rows_updated == 1

        row = audit_log.get_all_logs()[0]
        assert row["recovery_status"] == "RECOVERY_REQUIRED"
        assert row["rollback_recommended"] == 1
        assert row["recovery_reason"] == "Post-deployment health check failed."
        assert row["recovery_timestamp"] == "2026-07-16T00:05:00+00:00"
        # existing fields from the original decision must be untouched
        assert row["risk_level"] == "Low"
        assert row["decision"] == "approve"

    def test_update_recovery_unknown_deployment_id_does_not_crash(self, isolated_db):
        rows_updated = audit_log.update_recovery(
            deployment_id="does-not-exist",
            recovery_status="NOT_REQUIRED",
            rollback_recommended=False,
            recovery_reason="Health check passed.",
            recovery_timestamp="2026-07-16T00:05:00+00:00",
        )
        assert rows_updated == 0


class TestDeploymentVerificationEndpointRecovery:
    def test_healthy_response_includes_recovery_fields_and_no_rollback(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "recovery-test-001",
                "health_status": "healthy",
                "http_status_code": 200,
                "health_check": {"status": "healthy"},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["deployment_status"] == "success"  # DEV-009 contract unchanged
        assert body["recovery_status"] == "NOT_REQUIRED"
        assert body["rollback_recommended"] is False

        row = audit_log.get_all_logs()[0]
        assert row["recovery_status"] == "NOT_REQUIRED"
        assert row["rollback_recommended"] == 0

    def test_unhealthy_response_includes_recovery_fields_and_recommends_rollback(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "recovery-test-001",
                "health_status": "unhealthy",
                "http_status_code": 503,
                "health_check": {"status": "unhealthy", "database": "unreachable"},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["deployment_status"] == "failed"  # DEV-009 contract unchanged
        assert body["recovery_status"] == "RECOVERY_REQUIRED"
        assert body["rollback_recommended"] is True
        assert body["recovery_reason"]
        assert body["recommended_action"] == (
            "Rollback to previous stable deployment or redeploy after fixing the issue."
        )

        row = audit_log.get_all_logs()[0]
        assert row["recovery_status"] == "RECOVERY_REQUIRED"
        assert row["rollback_recommended"] == 1
        assert row["recovery_reason"]
        assert row["recovery_timestamp"]

    def test_unknown_deployment_id_still_does_not_crash(self, isolated_db):
        response = client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "does-not-exist",
                "health_status": "unhealthy",
                "http_status_code": 500,
            },
        )
        assert response.status_code == 200
        assert response.json()["recovery_status"] == "RECOVERY_REQUIRED"


class TestEmailTriggering:
    def test_recovery_required_email_fires_on_unhealthy_verification(self, isolated_db, monkeypatch):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        calls = []
        monkeypatch.setattr(
            api, "notify_recovery_required",
            lambda **kwargs: calls.append(kwargs),
        )

        client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "recovery-test-001",
                "health_status": "unhealthy",
                "http_status_code": 503,
                "health_check": {"status": "unhealthy"},
            },
        )

        assert len(calls) == 1
        assert calls[0]["deployment_id"] == "recovery-test-001"
        assert calls[0]["rollback_recommended"] is True
        assert calls[0]["recommended_action"] == (
            "Rollback to previous stable deployment or redeploy after fixing the issue."
        )

    def test_recovery_required_email_does_not_fire_on_healthy_verification(self, isolated_db, monkeypatch):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")

        calls = []
        monkeypatch.setattr(
            api, "notify_recovery_required",
            lambda **kwargs: calls.append(kwargs),
        )

        client.post(
            "/deployment-verification",
            headers=HEADERS,
            json={
                "deployment_id": "recovery-test-001",
                "health_status": "healthy",
                "http_status_code": 200,
                "health_check": {"status": "healthy"},
            },
        )

        assert len(calls) == 0

    def test_notify_recovery_required_no_credentials_does_not_raise(self, monkeypatch):
        """Mirrors the graceful no-op behavior of every other notify_* function
        when GMAIL_ADDRESS/GMAIL_APP_PASSWORD aren't configured."""
        monkeypatch.setattr(email_notify, "GMAIL_ADDRESS", None)
        monkeypatch.setattr(email_notify, "GMAIL_APP_PASSWORD", None)
        email_notify.notify_recovery_required(
            deployment_id="d-3",
            recovery_reason="Post-deployment health check failed.",
            rollback_recommended=True,
            recommended_action="Rollback to previous stable deployment or redeploy after fixing the issue.",
            health_check={"status": "unhealthy"},
        )


class TestDashboardCompatibility:
    """dashboard.py runs Streamlit calls at import time, so it can't be
    imported directly in a pytest process -- instead this confirms the
    exact data contract dashboard.py relies on (the row keys/shapes it
    reads via deployment_status_label/recovery_status_label logic)."""

    def test_row_without_recovery_fields_yields_none_not_a_crash(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")
        row = audit_log.get_all_logs()[0]
        assert row["recovery_status"] is None
        assert row["rollback_recommended"] in (None, 0)
        assert row["recovery_reason"] is None
        assert row["recovery_timestamp"] is None

    def test_row_with_recovery_required_has_all_fields_dashboard_reads(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")
        audit_log.update_recovery(
            deployment_id="recovery-test-001",
            recovery_status="RECOVERY_REQUIRED",
            rollback_recommended=True,
            recovery_reason="Post-deployment health check failed.",
            recovery_timestamp="2026-07-16T00:05:00+00:00",
        )
        row = audit_log.get_all_logs()[0]
        assert row["recovery_status"] == "RECOVERY_REQUIRED"
        assert row["rollback_recommended"] == 1
        assert row["recovery_reason"]


class TestBackwardCompatibility:
    """DEV-010 must not disturb DEV-009's contract or any earlier endpoint."""

    def test_predict_endpoint_still_present(self):
        assert any(route.path == "/predict" for route in api.app.routes)

    def test_health_endpoint_unaffected(self, isolated_db):
        response = client.get("/health")
        assert response.status_code in (200, 503)
        assert "status" in response.json()

    def test_no_new_endpoint_created_for_recovery(self):
        """The ticket is explicit: extend /deployment-verification, do not add a new route."""
        paths = {route.path for route in api.app.routes}
        assert "/deployment-verification" in paths
        assert not any("recovery" in p and p != "/deployment-verification" for p in paths)

    def test_old_shaped_row_without_verification_or_recovery_fields_still_reads_fine(self, isolated_db):
        audit_log.log_decision(SAMPLE_DEPLOYMENT, SAMPLE_RESULT, decision="approve")
        row = audit_log.get_all_logs()[0]
        assert row["deployment_status"] is None
        assert row["recovery_status"] is None
