"""
test_ml_integration.py

DEV-002: demonstrates and verifies the full live prediction pipeline --

    deployment -> feature engineering -> ML predictor -> decision engine
               -> Groq explanation -> merged response

via risk_scorer.score_deployment(), the exact orchestration api.py's
/predict handler calls. Like test_risk_scorer.py, this runs with a
dummy GROQ_API_KEY (set by test_api_auth.py, which always collects
first) so it's fast and deterministic in CI -- the point being proven
is that risk_level/confidence/decision come from the ML model and
decision_engine regardless of whether Groq is reachable.

For a live, non-degraded demonstration with a real explanation, run
this file directly with a real GROQ_API_KEY configured in .env:
    python3 test_ml_integration.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("GROQ_API_KEY", "test-key-for-non-network-tests")

from decision_engine import RISK_TO_DECISION, decide_action

SAMPLE_LOW_RISK = {
    "author": "meena", "team": "search", "files_changed": 3, "lines_changed": 40,
    "test_coverage_pct": 95.0, "tests_failed": 0, "environment": "staging",
    "day_of_week": "Tue", "hour": 11, "changed_files": ["app/search_index.py"],
}

SAMPLE_HIGH_RISK = {
    "author": "sanjay", "team": "payments", "files_changed": 80, "lines_changed": 3000,
    "test_coverage_pct": 40.0, "tests_failed": 4, "environment": "production",
    "day_of_week": "Fri", "hour": 21, "changed_files": ["app/payment_gateway.py", "app/config/prod.env"],
}


def test_decision_engine_mapping_matches_ticket_spec():
    assert RISK_TO_DECISION == {"Low": "approve", "Medium": "delay", "High": "reject"}
    assert decide_action("Low") == "approve"
    assert decide_action("Medium") == "delay"
    assert decide_action("High") == "reject"
    assert decide_action("Unknown") == "delay"  # fails toward caution, not silent approval


def test_full_pipeline_produces_internally_consistent_response():
    import risk_scorer

    for sample in (SAMPLE_LOW_RISK, SAMPLE_HIGH_RISK):
        result = risk_scorer.score_deployment(sample, max_retries=1)

        # ML stage
        assert result["risk_level"] in ("Low", "Medium", "High")
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["model"] == "RandomForest"
        assert result["model_version"] == "1.0"

        # decision engine stage -- decision must match risk_level via the
        # one dedicated mapping function, never an independently
        # recomputed rule elsewhere
        assert result["decision"] == decide_action(result["risk_level"])

        # Groq explanation stage -- always present, real or degraded
        assert result["reasoning"]
        assert result["suggested_action"]
        assert "prompt_version" in result
        assert isinstance(result["degraded"], bool)


if __name__ == "__main__":
    # Human-readable walk through the full pipeline. Run with a real
    # GROQ_API_KEY set to see a live, non-degraded explanation instead
    # of the CI-safe degraded fallback pytest exercises above.
    import risk_scorer

    for label, sample in (("LOW-risk-shaped", SAMPLE_LOW_RISK), ("HIGH-risk-shaped", SAMPLE_HIGH_RISK)):
        print(f"\n=== {label} deployment ===")
        print("Input:", sample)
        result = risk_scorer.score_deployment(sample)
        print("Response:", result)
