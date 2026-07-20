"""
audit_log.py

Purpose: creates and writes to the database that records every risk
decision made by the API. This is what turns "the AI made a decision
once" into "we have a reviewable history of every decision," which is
what the brief calls the audit trail, and what the dashboard reads from.

Backed by Neon (managed Postgres) via SQLAlchemy -- see database.py for
the engine/session and models.py for the AuditLog table definition.
Every function below keeps its original name, signature, and return
shape, so callers (api.py, dashboard.py, accuracy_metrics.py) don't know
or care what's behind them.
"""

import json
from datetime import datetime
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError
from database import engine, SessionLocal, Base
from models import AuditLog


# Columns added after the table's first deployment to Neon --
# Base.metadata.create_all() below only creates a table that doesn't
# exist yet, it never ALTERs an existing one, so new columns need their
# own migration step. SQLite (used by the test suite's isolated_db
# fixture) doesn't support "ADD COLUMN IF NOT EXISTS", so existence is
# checked explicitly via inspect() instead of relying on that syntax --
# works the same way against both SQLite and Postgres.
_NEW_COLUMNS = [
    ("lines_changed", "INTEGER"),
    ("tests_failed", "INTEGER"),
    ("changed_files", "TEXT"),
    ("day_of_week", "TEXT"),
    ("hour", "INTEGER"),
    ("threshold_override", "INTEGER"),
    ("threshold_reason", "TEXT"),
    ("triggered_thresholds", "TEXT"),
]


def init_db():
    """
    Creates the audit_log table if it doesn't already exist, then adds
    any columns that were introduced after the table's first deploy.
    Safe to call every time the API starts -- won't wipe existing data.
    """
    Base.metadata.create_all(bind=engine)

    existing_columns = {col["name"] for col in inspect(engine).get_columns("audit_log")}
    with engine.begin() as conn:
        for name, col_type in _NEW_COLUMNS:
            if name not in existing_columns:
                conn.execute(text(f"ALTER TABLE audit_log ADD COLUMN {name} {col_type}"))


def check_connection() -> bool:
    """
    DEV-009: lightweight liveness check for /health -- opens a connection
    and runs a trivial query, without pulling the whole audit_log table
    (get_all_logs() would work but is unnecessarily heavy for a health
    probe that may be hit by uptime monitors).
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def log_decision(deployment: dict, result: dict, decision: str):
    """
    Writes one row: the deployment's details, what the AI decided, and
    when. Called every time /predict runs. actual_outcome and
    incident_severity start empty -- they get filled in later when we
    find out what really happened (the feedback loop piece).

    Also persists the full ML + policy + threshold traceability trail
    (confidence, model, model_version, policy_override, policy_reason,
    triggered_policies, threshold_override, threshold_reason,
    triggered_thresholds) so an auditor can reconstruct exactly why a
    deployment received its final decision without needing to re-run the
    pipeline. Extra keys result might carry are ignored via .get() --
    this stays safe even if callers pass an older, smaller result dict.
    """
    session = SessionLocal()
    try:
        session.add(AuditLog(
            deployment_id=deployment.get("deployment_id"),
            author=deployment.get("author"),
            team=deployment.get("team"),
            files_changed=deployment.get("files_changed"),
            lines_changed=deployment.get("lines_changed"),
            test_coverage_pct=deployment.get("test_coverage_pct"),
            tests_failed=deployment.get("tests_failed"),
            changed_files=json.dumps(deployment.get("changed_files") or []),
            day_of_week=deployment.get("day_of_week"),
            hour=deployment.get("hour"),
            environment=deployment.get("environment"),
            risk_level=result.get("risk_level"),
            reasoning=result.get("reasoning"),
            suggested_action=result.get("suggested_action"),
            decision=decision,
            actual_outcome=None,   # unknown yet at decision time
            incident_severity=None,   # unknown yet at decision time
            prompt_version=result.get("prompt_version"),
            degraded=1 if result.get("degraded") else 0,
            failed_at_stage=deployment.get("failed_at_stage"),
            pipeline_stage_success_ratio=deployment.get("pipeline_stage_success_ratio"),
            confidence=result.get("confidence"),
            model=result.get("model"),
            model_version=result.get("model_version"),
            policy_override=1 if result.get("policy_override") else 0,
            policy_reason=result.get("policy_reason"),
            triggered_policies=json.dumps(result.get("triggered_policies") or []),
            threshold_override=1 if result.get("threshold_override") else 0,
            threshold_reason=result.get("threshold_reason"),
            triggered_thresholds=json.dumps(result.get("triggered_thresholds") or []),
            created_at=datetime.now().isoformat(),
        ))
        session.commit()
    finally:
        session.close()


def update_outcome(deployment_id: str, actual_outcome: str, incident_severity: str = "none"):
    """
    Call this once the real outcome is known (success/fail), to close
    the feedback loop -- this is what lets the dashboard later show
    'predicted vs actual' accuracy.
    """
    session = SessionLocal()
    try:
        session.query(AuditLog).filter(AuditLog.deployment_id == deployment_id).update(
            {"actual_outcome": actual_outcome, "incident_severity": incident_severity},
            synchronize_session=False,
        )
        session.commit()
    finally:
        session.close()


def update_verification(deployment_id: str, deployment_status: str, health_check: dict, verification_time: str):
    """
    DEV-009: records the result of the post-deployment health check
    against the audit log row it belongs to. Called by
    POST /deployment-verification once the Azure Pipeline has waited for
    the deployment to settle and called GET /health.

    deployment_status: "success" | "failed" -- derived from whether
        GET /health returned HTTP 200.
    health_check: the raw /health response body (or a best-effort
        fallback if the response wasn't valid JSON), stored JSON-encoded
        the same way triggered_policies is.
    verification_time: ISO timestamp of when the check was performed.
    """
    session = SessionLocal()
    try:
        rows_updated = session.query(AuditLog).filter(AuditLog.deployment_id == deployment_id).update(
            {
                "deployment_status": deployment_status,
                "health_check": json.dumps(health_check) if health_check is not None else None,
                "verification_time": verification_time,
            },
            synchronize_session=False,
        )
        session.commit()
        return rows_updated
    finally:
        session.close()


def update_recovery(deployment_id: str, recovery_status: str, rollback_recommended: bool,
                     recovery_reason: str, recovery_timestamp: str):
    """
    DEV-010: records the recovery_manager's evaluation of a failed (or
    healthy) post-deployment health check against the audit log row it
    belongs to. Called by POST /deployment-verification right after
    update_verification(), so both the raw health check result and the
    resulting recovery recommendation live on the same row.

    No Azure rollback happens here -- this only persists the
    recommendation for the dashboard/audit trail.
    """
    session = SessionLocal()
    try:
        rows_updated = session.query(AuditLog).filter(AuditLog.deployment_id == deployment_id).update(
            {
                "recovery_status": recovery_status,
                "rollback_recommended": 1 if rollback_recommended else 0,
                "recovery_reason": recovery_reason,
                "recovery_timestamp": recovery_timestamp,
            },
            synchronize_session=False,
        )
        session.commit()
        return rows_updated
    finally:
        session.close()


def get_all_logs():
    """Returns every logged decision -- this is what the dashboard will call."""
    session = SessionLocal()
    try:
        rows = session.query(AuditLog).order_by(AuditLog.created_at.desc()).all()
        result = [
            {column.name: getattr(row, column.name) for column in AuditLog.__table__.columns}
            for row in rows
        ]
    finally:
        session.close()

    # triggered_policies is stored as a JSON-encoded string (same as it
    # was in SQLite); decode it back into a real list here so callers --
    # api.py's /history response and the dashboard -- see an actual JSON
    # array, not a string. Rows written before this column existed (or
    # where it's otherwise NULL) decode to an empty list rather than error.
    for row in result:
        raw = row.get("triggered_policies")
        try:
            row["triggered_policies"] = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            row["triggered_policies"] = []

        raw_health_check = row.get("health_check")
        try:
            row["health_check"] = json.loads(raw_health_check) if raw_health_check else None
        except (TypeError, ValueError):
            row["health_check"] = None

        raw_changed_files = row.get("changed_files")
        try:
            row["changed_files"] = json.loads(raw_changed_files) if raw_changed_files else []
        except (TypeError, ValueError):
            row["changed_files"] = []

        raw_triggered_thresholds = row.get("triggered_thresholds")
        try:
            row["triggered_thresholds"] = json.loads(raw_triggered_thresholds) if raw_triggered_thresholds else []
        except (TypeError, ValueError):
            row["triggered_thresholds"] = []

    return result


if __name__ == "__main__":
    # running this file directly just sets up the empty table, useful
    # for a first-time check that everything works
    init_db()
    print("Database ready (Neon Postgres)")
    print(f"Existing rows: {len(get_all_logs())}")
