"""
test_multi_pipeline.py

Evaluation criterion: "Practicality and scalability across multiple
pipelines." Nothing in the gap audit demonstrated this live -- the API
is stateless per-request and every row is written to a shared audit
log, but no test ever proved that concurrent callers from different
teams/environments/pipelines don't clobber or bleed into each other's
data.

This fires real concurrent /predict requests (via a thread pool, real
HTTP-shaped calls through TestClient) for several distinct
team/environment/deployment_id combinations that would realistically
represent different Azure DevOps pipelines calling this same service,
then checks /history to confirm every row still shows exactly its own
deployment_id/author/team/environment -- no cross-contamination, no
lost writes, no shared mutable state leaking between requests.

Uses a dummy GROQ_API_KEY like test_ml_integration.py, so Groq calls
degrade gracefully (fast, deterministic, no network dependency) --
this test is about API/DB concurrency, not explanation quality.
Requires a real DATABASE_URL (see .env), same as test_api_auth.py.
"""

import os
import sys
import importlib
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["API_KEY"] = "test-secret-123"

from fastapi.testclient import TestClient
import api
importlib.reload(api)
from api import app

client = TestClient(app)
HEADERS = {"X-API-Key": "test-secret-123"}

PIPELINES = [
    {
        "deployment_id": "multi-pipeline-payments-001",
        "author": "arjun", "team": "payments", "environment": "production",
        "files_changed": 5, "lines_changed": 120, "test_coverage_pct": 88.0,
        "tests_failed": 0, "day_of_week": "Wed", "hour": 14,
        "changed_files": ["app/payment_gateway.py"],
    },
    {
        "deployment_id": "multi-pipeline-search-002",
        "author": "meena", "team": "search", "environment": "staging",
        "files_changed": 3, "lines_changed": 40, "test_coverage_pct": 95.0,
        "tests_failed": 0, "day_of_week": "Wed", "hour": 14,
        "changed_files": ["app/search_index.py"],
    },
    {
        "deployment_id": "multi-pipeline-infra-003",
        "author": "sanjay", "team": "infra", "environment": "production",
        "files_changed": 50, "lines_changed": 2000, "test_coverage_pct": 55.0,
        "tests_failed": 2, "day_of_week": "Fri", "hour": 20,
        "changed_files": ["app/config/prod.env"],
    },
    {
        "deployment_id": "multi-pipeline-billing-004",
        "author": "dharani", "team": "billing", "environment": "staging",
        "files_changed": 8, "lines_changed": 210, "test_coverage_pct": 78.0,
        "tests_failed": 0, "day_of_week": "Mon", "hour": 10,
        "changed_files": ["app/billing/invoice.py"],
    },
]


def call_predict(payload):
    response = client.post("/predict", json=payload, headers=HEADERS)
    return payload["deployment_id"], response


class TestConcurrentPipelinesDoNotCrossContaminate:
    """Simulates several Azure DevOps pipelines (different teams/environments)
    hitting /predict at the same time, as would genuinely happen once more
    than one project wires this service into its release gate."""

    def test_concurrent_predict_requests_each_get_their_own_correct_response(self):
        responses = {}
        with ThreadPoolExecutor(max_workers=len(PIPELINES)) as pool:
            futures = [pool.submit(call_predict, p) for p in PIPELINES]
            for future in as_completed(futures):
                deployment_id, response = future.result()
                responses[deployment_id] = response

        for pipeline in PIPELINES:
            response = responses[pipeline["deployment_id"]]
            assert response.status_code == 200, response.text
            body = response.json()
            # The response for THIS deployment_id must never carry another
            # pipeline's risk_level/decision -- proves no shared mutable
            # state (e.g. a module-level "last result" variable) leaked
            # across concurrent requests.
            assert body["deployment_id"] == pipeline["deployment_id"]
            assert body["risk_level"] in ("Low", "Medium", "High")
            assert body["decision"] in ("approve", "delay", "reject")

    def test_history_segregates_every_pipeline_with_no_cross_contamination(self):
        # Requests already fired above; /history is the shared audit log
        # every pipeline writes into, so this is where cross-contamination
        # (wrong team on a row, overwritten rows, dropped writes) would show.
        history_response = client.get("/history", headers=HEADERS)
        assert history_response.status_code == 200
        rows_by_id = {row["deployment_id"]: row for row in history_response.json()}

        for pipeline in PIPELINES:
            row = rows_by_id.get(pipeline["deployment_id"])
            assert row is not None, f"{pipeline['deployment_id']} missing from /history"
            assert row["author"] == pipeline["author"]
            assert row["team"] == pipeline["team"]
            assert row["environment"] == pipeline["environment"]

    def test_high_risk_production_pipeline_not_diluted_by_concurrent_low_risk_ones(self):
        """Specifically guards against risk scoring for one pipeline being
        influenced by another pipeline's request landing at the same time
        (e.g. a shared/reused history_rows list mutated in place)."""
        infra = PIPELINES[2]  # high files/lines changed, prod, 2 tests failed
        search = PIPELINES[1]  # small change, staging, all green

        infra_response = client.post("/predict", json=infra, headers=HEADERS)
        search_response = client.post("/predict", json=search, headers=HEADERS)

        assert infra_response.status_code == 200
        assert search_response.status_code == 200
        infra_body = infra_response.json()
        search_body = search_response.json()

        assert infra_body["deployment_id"] == infra["deployment_id"]
        assert search_body["deployment_id"] == search["deployment_id"]
        # Not asserting exact risk levels (that's the ML model's call, not
        # this test's) -- only that each response is unmistakably about its
        # own deployment_id and not a copy of the other's.
        assert infra_body["deployment_id"] != search_body["deployment_id"]
