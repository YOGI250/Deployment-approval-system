"""
test_api_auth.py

Tests the API key authentication layer specifically -- this is a security
control, so it deserves its own explicit tests rather than being assumed
to work. Run with:
    pytest tests/test_api_auth.py -v
"""

import os
import sys
import importlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["API_KEY"] = "test-secret-123"

from fastapi.testclient import TestClient
import api
importlib.reload(api)  # reload so it picks up the API_KEY set above
from api import app

client = TestClient(app)


def test_history_rejects_missing_key():
    response = client.get("/history")
    assert response.status_code == 401


def test_history_rejects_wrong_key():
    response = client.get("/history", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_history_accepts_correct_key():
    response = client.get("/history", headers={"X-API-Key": "test-secret-123"})
    assert response.status_code == 200


def test_outcome_endpoint_requires_auth():
    response = client.post("/outcome", json={"deployment_id": "x", "actual_outcome": "success"})
    assert response.status_code == 401


def test_health_check_does_not_require_auth():
    """The root health-check endpoint should stay open -- useful for uptime monitors."""
    response = client.get("/")
    assert response.status_code == 200


def test_failure_rate_impact_rejects_missing_key():
    """Derived from the same audit log /history protects, so it needs the same key."""
    response = client.get("/failure-rate-impact")
    assert response.status_code == 401


def test_failure_rate_impact_accepts_correct_key():
    response = client.get("/failure-rate-impact", headers={"X-API-Key": "test-secret-123"})
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"baseline_fail_rate", "actual_fail_rate", "sample_size", "reduction_pct"}
    # The 500-row starter history always exists in this repo, so baseline is
    # always a real number -- never null in practice.
    assert body["baseline_fail_rate"] is not None
