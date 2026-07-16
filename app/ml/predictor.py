"""
predictor.py

Inference only. Loads the trained model from data/model.pkl and turns
already-engineered features into a risk prediction. Never trains --
see train_model.py for that. Never calls Groq, never calls FastAPI,
never imports api.py -- this module works standalone.

Not wired into api.py yet (DEV-001 is foundation only).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # app/ml -- for model_utils

from model_utils import load_model, features_to_vector, MODEL_NAME, MODEL_VERSION, MODEL_PATH

_model = None


def _get_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"No trained model found at {MODEL_PATH}. Run train_model.py first."
            )
        _model = load_model()
    return _model


def predict(features: dict) -> dict:
    """
    Accepts an already-engineered feature dict (see
    feature_engineering.build_features) and returns:
        {
            "risk_level": "Low" | "Medium" | "High",
            "confidence": 0.xx,
            "model": "RandomForest",
            "model_version": "1.0",
        }
    """
    model = _get_model()
    vector = features_to_vector(features)

    risk_level = str(model.predict([vector])[0])
    probabilities = model.predict_proba([vector])[0]
    confidence = round(float(max(probabilities)), 2)

    return {
        "risk_level": risk_level,
        "confidence": confidence,
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
    }
