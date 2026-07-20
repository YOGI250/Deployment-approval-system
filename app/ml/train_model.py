"""
train_model.py

Trains the Random Forest deployment-risk classifier from
data/deployment_history.csv, blended with real outcomes recorded in the
audit log (see load_real_audit_rows()), and saves it to data/model.pkl.

Run manually (from app/ml/, or anywhere -- paths are resolved
relative to this file):
    python3 train_model.py

This is the ONLY place model training happens. predictor.py never
trains -- it only loads the file this script produces. The prediction
API must never train the model (training and inference are strictly
separate responsibilities).

This script is standalone: no FastAPI import, no Groq import, no
api.py import. It does import audit_log.py (for real outcomes), but
only inside a try/except -- if DATABASE_URL isn't configured (local
dev, CI without DB secrets) it silently falls back to training on the
synthetic CSV alone, exactly like before this feature existed.
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


def load_real_audit_rows() -> list:
    """
    Pulls real deployments with a known actual_outcome from the audit
    log, so the model can learn from genuine production results instead
    of only ever seeing the synthetic starter CSV. Returns [] if the
    database isn't configured or reachable, so this script stays
    runnable standalone (local dev, CI without DB secrets) -- the same
    fallback stance scheduled_maintenance.py takes for each of its
    steps.

    Rows already carry files_changed/lines_changed/test_coverage_pct/
    tests_failed/changed_files/day_of_week/hour/environment/
    pipeline_stage_success_ratio directly (audit_log.py persists these
    on every /predict call), so they need no reshaping to go through
    build_features() the same way a CSV row does.
    """
    try:
        import audit_log
        rows = audit_log.get_all_logs()
    except Exception as exc:
        print(f"Skipping real audit-log data (unavailable): {exc}")
        return []

    return [row for row in rows if row.get("actual_outcome")]


def _as_history_entry(row: dict) -> dict:
    """
    Shapes a row (CSV or real audit-log) into the minimal author/team/
    outcome form calculate_author_success_rate/calculate_team_success_rate
    expect. CSV rows already use "outcome"; real audit-log rows use
    "actual_outcome" instead (see audit_log.update_outcome()) -- same
    normalization api.py's get_combined_history() does for live scoring.
    """
    return {
        "author": row.get("author"),
        "team": row.get("team"),
        "outcome": row.get("outcome", row.get("actual_outcome")),
    }


def load_training_data():
    """
    Builds (X, y) from deployment_history.csv blended with real,
    outcome-verified audit-log rows. author_recent_success_rate for each
    row is computed leave-one-out (history_rows excludes the row itself)
    against the combined pool, so a row's own outcome never informs its
    own feature, and a real author's success rate reflects both the
    synthetic baseline and their own genuine track record.
    """
    with open(HISTORY_CSV_PATH) as f:
        csv_rows = list(csv.DictReader(f))

    real_rows = load_real_audit_rows()
    rows = csv_rows + real_rows
    history_pool = [_as_history_entry(r) for r in rows]

    X, y = [], []
    for i, row in enumerate(rows):
        other_history = history_pool[:i] + history_pool[i + 1:]
        features = build_features(row, history_rows=other_history)
        X.append(features_to_vector(features))
        y.append(derive_risk_label({
            "outcome": row.get("outcome", row.get("actual_outcome")),
            "incident_severity": row.get("incident_severity"),
        }))

    return X, y, len(csv_rows), len(real_rows)


def train():
    X, y, n_csv, n_real = load_training_data()

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X, y)

    save_model(model)

    train_accuracy = model.score(X, y)
    print(f"Trained on {len(X)} rows: {n_csv} from {HISTORY_CSV_PATH} + {n_real} real audit-log outcomes")
    print(f"Training accuracy: {train_accuracy:.1%}")
    print(f"Saved model -> {MODEL_PATH}")


if __name__ == "__main__":
    train()
