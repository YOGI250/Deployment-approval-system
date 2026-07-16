"""
train_model.py

Trains the Random Forest deployment-risk classifier from
data/deployment_history.csv and saves it to data/model.pkl.

Run manually (from app/ml/, or anywhere -- paths are resolved
relative to this file):
    python3 train_model.py

This is the ONLY place model training happens. predictor.py never
trains -- it only loads the file this script produces. The prediction
API must never train the model (training and inference are strictly
separate responsibilities).

This script is standalone: no FastAPI import, no Groq import, no
api.py import.
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # app/ml -- for model_utils
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # app -- for feature_engineering

from sklearn.ensemble import RandomForestClassifier

from feature_engineering import build_features
from model_utils import features_to_vector, save_model, MODEL_PATH, DATA_DIR

HISTORY_CSV_PATH = os.path.join(DATA_DIR, "deployment_history.csv")


def derive_risk_label(row: dict) -> str:
    """
    deployment_history.csv has no risk_level column -- only outcome
    (success/fail) and incident_severity (none/minor/major). Derives a
    3-class training label from those, mirroring the same severity
    tiers the existing Groq prompt already uses:
        outcome == success                        -> Low
        outcome == fail, incident_severity major   -> High
        outcome == fail, incident_severity minor/none -> Medium
    """
    if row.get("outcome") != "fail":
        return "Low"
    return "High" if row.get("incident_severity") == "major" else "Medium"


def load_training_data():
    """
    Builds (X, y) from deployment_history.csv. author_recent_success_rate
    for each row is computed leave-one-out (history_rows excludes the
    row itself) so a row's own outcome never informs its own feature.
    """
    with open(HISTORY_CSV_PATH) as f:
        rows = list(csv.DictReader(f))

    X, y = [], []
    for i, row in enumerate(rows):
        other_rows = rows[:i] + rows[i + 1:]
        features = build_features(row, history_rows=other_rows)
        X.append(features_to_vector(features))
        y.append(derive_risk_label(row))

    return X, y


def train():
    X, y = load_training_data()

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X, y)

    save_model(model)

    train_accuracy = model.score(X, y)
    print(f"Trained on {len(X)} rows from {HISTORY_CSV_PATH}")
    print(f"Training accuracy: {train_accuracy:.1%}")
    print(f"Saved model -> {MODEL_PATH}")


if __name__ == "__main__":
    train()
