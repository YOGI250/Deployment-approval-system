"""
model_info.py

Purpose: IMP-002 -- gathers real, verifiable facts about the currently
deployed ML model for the dashboard's "Model Information" section.

Nothing here is invented. Every field comes from exactly one of:
  - the loaded model artifact itself (data/model.pkl's sklearn attributes)
  - an optional metadata sidecar file (data/model_metadata.json), which
    does not exist in this repo today -- train_model.py only prints
    training-set accuracy to stdout, it never persists a held-out
    validation metric or the exact training row count anywhere. If a
    future training run starts writing that file, its fields are picked
    up automatically; until then, those two fields are honestly "N/A".
  - the model file's filesystem mtime

Deliberately NOT done: inferring training dataset size from the
RandomForest's tree internals (e.g. estimators_[i].tree_.n_node_samples[0]).
That was checked and rejected -- with bootstrap=True, the root-node
sample count differs per tree and does not reliably reconstruct the
original training set size. Using it would be guessing dressed up as a
real number, which the ticket explicitly forbids.
"""

import os
import json
from datetime import datetime, timezone

from ml.predictor import _get_model, MODEL_NAME, MODEL_VERSION, MODEL_PATH
from risk_scorer import PROMPT_VERSION

NOT_AVAILABLE = "N/A"

# Optional, currently-unpopulated sidecar file. Its absence is the normal
# case today -- never treated as an error.
METADATA_PATH = os.path.join(os.path.dirname(MODEL_PATH), "model_metadata.json")


def _load_metadata_file() -> dict:
    try:
        with open(METADATA_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _number_of_features(model):
    """
    Prefers feature_names_in_ (only populated when a model was fit on a
    pandas DataFrame with named columns -- not our case, since training
    uses plain numeric vectors, but a future retrain might change that)
    and falls back to n_features_in_, exactly as the ticket specifies.
    """
    feature_names = getattr(model, "feature_names_in_", None)
    if feature_names is not None:
        return len(feature_names)
    n_features = getattr(model, "n_features_in_", None)
    if n_features is not None:
        return int(n_features)
    return NOT_AVAILABLE


def _model_last_updated() -> str:
    try:
        mtime = os.path.getmtime(MODEL_PATH)
    except OSError:
        return NOT_AVAILABLE
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def get_model_info() -> dict:
    """
    Returns a flat, display-ready dict for the Model Information panel.
    Every field is either a real value or the literal string "N/A" --
    never a fabricated or estimated one.
    """
    metadata = _load_metadata_file()

    try:
        model = _get_model()
        number_of_features = _number_of_features(model)
    except Exception:
        # Same failure mode /health already tolerates -- the panel
        # degrades to N/A instead of crashing the whole dashboard.
        number_of_features = NOT_AVAILABLE

    return {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "training_dataset_size": metadata.get("training_dataset_size", NOT_AVAILABLE),
        "number_of_features": number_of_features,
        "offline_validation_accuracy": metadata.get("offline_validation_accuracy", NOT_AVAILABLE),
        "model_last_updated": _model_last_updated(),
    }
