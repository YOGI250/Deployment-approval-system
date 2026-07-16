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
