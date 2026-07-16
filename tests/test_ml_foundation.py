"""
test_ml_foundation.py

Demonstrates the DEV-001 ML foundation pipeline end to end:

    deployment data -> feature engineering -> predictor -> risk prediction

Does not import, start, or call api.py / the FastAPI app / risk_scorer.py
in any way -- this is proof the ML foundation works fully standalone.

Requires data/model.pkl to already exist -- run app/ml/train_model.py
first if it's missing.

Run directly:
    python3 test_ml_foundation.py
Or via pytest:
    pytest tests/test_ml_foundation.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "ml"))

from feature_engineering import build_features
from predictor import predict

# A deliberately risky sample: many files changed, low coverage, a
# failed test, a critical file touched, late Friday deploy.
SAMPLE_DEPLOYMENT = {
    "author": "priya",
    "team": "payments",
    "files_changed": 65,
    "lines_changed": 1800,
    "test_coverage_pct": 52.0,
    "tests_failed": 2,
    "environment": "production",
    "day_of_week": "Fri",
    "hour": 19,
    "changed_files": ["app/payment_gateway.py", "app/config/settings.py"],
}


def test_pipeline_produces_valid_prediction():
    features = build_features(SAMPLE_DEPLOYMENT)
    result = predict(features)

    assert result["risk_level"] in ("Low", "Medium", "High")
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["model"] == "RandomForest"
    assert result["model_version"] == "1.0"


if __name__ == "__main__":
    print("Deployment data:", SAMPLE_DEPLOYMENT)

    features = build_features(SAMPLE_DEPLOYMENT)
    print("\nEngineered features:", features)

    result = predict(features)
    print("\nPrediction:", result)
