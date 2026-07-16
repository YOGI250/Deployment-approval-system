"""
model_utils.py

Shared between train_model.py and predictor.py: canonical feature
ordering (named dict -> numeric vector) and model (de)serialization.
Kept in one place so training and inference can never drift out of
sync on either the feature order or the storage path/format.
"""

import os
import pickle

ML_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ML_DIR, "..", "..", "data")
MODEL_PATH = os.path.join(DATA_DIR, "model.pkl")

MODEL_NAME = "RandomForest"
MODEL_VERSION = "1.0"

# Fixed order the trained model's input vector corresponds to
# positionally. Must match feature_engineering.build_features()'s keys
# exactly -- if a key is added/removed there, update this list and
# retrain (train_model.py and predictor.py both import this constant,
# so they can't disagree on order).
FEATURE_ORDER = [
    "files_changed",
    "lines_changed",
    "test_coverage_pct",
    "tests_failed",
    "author_recent_success_rate",
    "has_critical_files",
    "is_risky_timing",
    "is_production",
    "pipeline_stage_success_ratio",
]


def features_to_vector(feature_dict: dict) -> list:
    """Converts a named feature dict into the ordered numeric vector the model expects."""
    missing = [k for k in FEATURE_ORDER if k not in feature_dict]
    if missing:
        raise ValueError(f"feature_dict is missing required keys: {missing}")
    return [feature_dict[k] for k in FEATURE_ORDER]


def save_model(model, path: str = MODEL_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)


def load_model(path: str = MODEL_PATH):
    with open(path, "rb") as f:
        return pickle.load(f)
