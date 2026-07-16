"""
audit_log.py

Purpose: creates and writes to a small local database (SQLite) that
records every risk decision made by the API. This is what turns
"the AI made a decision once" into "we have a reviewable history of
every decision," which is what the brief calls the audit trail, and
what the dashboard will read from later.

SQLite needs no separate server -- it's just a single file
(audit_log.db) that gets created automatically the first time you run
this.
"""

import sqlite3
import os
import json
from datetime import datetime

# Points to data/audit_log.db regardless of what directory this is run from
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_FILE = os.path.join(DATA_DIR, "audit_log.db")

# timeout=10 tells SQLite to wait up to 10 seconds for a lock to clear
# instead of failing immediately -- needed because api.py and dashboard.py
# are separate programs that both touch this same database file.
def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    return sqlite3.connect(DB_FILE, timeout=10)


def init_db():
    """
    Creates the audit_log table if it doesn't already exist.
    Safe to call every time the API starts -- won't wipe existing data.
    """
    conn = _connect()
    cursor = conn.cursor()
    # WAL mode lets one process write while another reads at the same time,
    # which is exactly our situation: api.py writes, dashboard.py reads,
    # as two separate running programs.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deployment_id TEXT,
            author TEXT,
            team TEXT,
            files_changed INTEGER,
            test_coverage_pct REAL,
            environment TEXT,
            risk_level TEXT,
            reasoning TEXT,
            suggested_action TEXT,
            decision TEXT,
            actual_outcome TEXT,
            incident_severity TEXT,
            prompt_version TEXT,
            degraded INTEGER DEFAULT 0,
            failed_at_stage TEXT,
            pipeline_stage_success_ratio REAL,
            confidence REAL,
            model TEXT,
            model_version TEXT,
            policy_override INTEGER DEFAULT 0,
            policy_reason TEXT,
            triggered_policies TEXT,
            deployment_status TEXT,
            health_check TEXT,
            verification_time TEXT,
            recovery_status TEXT,
            rollback_recommended INTEGER DEFAULT 0,
            recovery_reason TEXT,
            recovery_timestamp TEXT,
            created_at TEXT
        )
    """)
    conn.commit()

    # Simple migration: if this database already existed before a given
    # column was added (e.g. the one already running on Azure), add the
    # missing column rather than silently failing on the next insert. Safe
    # to run every time the API starts -- ALTER TABLE ADD COLUMN is a no-op
    # once the column already exists, and this whole block is skipped for
    # columns already present.
    cursor.execute("PRAGMA table_info(audit_log)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "prompt_version" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN prompt_version TEXT")
    if "degraded" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN degraded INTEGER DEFAULT 0")
    if "failed_at_stage" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN failed_at_stage TEXT")
    if "pipeline_stage_success_ratio" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN pipeline_stage_success_ratio REAL")
    if "confidence" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN confidence REAL")
    if "model" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN model TEXT")
    if "model_version" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN model_version TEXT")
    if "policy_override" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN policy_override INTEGER DEFAULT 0")
    if "policy_reason" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN policy_reason TEXT")
    if "triggered_policies" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN triggered_policies TEXT")
    # DEV-009: post-deployment health verification fields
    if "deployment_status" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN deployment_status TEXT")
    if "health_check" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN health_check TEXT")
    if "verification_time" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN verification_time TEXT")
    # DEV-010: deployment recovery framework fields
    if "recovery_status" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN recovery_status TEXT")
    if "rollback_recommended" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN rollback_recommended INTEGER DEFAULT 0")
    if "recovery_reason" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN recovery_reason TEXT")
    if "recovery_timestamp" not in existing_columns:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN recovery_timestamp TEXT")
    conn.commit()
    conn.close()


def check_connection() -> bool:
    """
    DEV-009: lightweight liveness check for /health -- opens a connection
    and runs a trivial query, without pulling the whole audit_log table
    (get_all_logs() would work but is unnecessarily heavy for a health
    probe that may be hit by uptime monitors).
    """
    try:
        conn = _connect()
        conn.execute("SELECT 1")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def log_decision(deployment: dict, result: dict, decision: str):
    """
    Writes one row: the deployment's details, what the AI decided, and
    when. Called every time /predict runs. actual_outcome and
    incident_severity start empty -- they get filled in later when we
    find out what really happened (the feedback loop piece).

    Also persists the full ML + policy traceability trail (confidence,
    model, model_version, policy_override, policy_reason,
    triggered_policies) so an auditor can reconstruct exactly why a
    deployment received its final decision without needing to re-run the
    pipeline. Extra keys result might carry are ignored via .get() --
    this stays safe even if callers pass an older, smaller result dict.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_log (
            deployment_id, author, team, files_changed, test_coverage_pct,
            environment, risk_level, reasoning, suggested_action, decision,
            actual_outcome, incident_severity, prompt_version, degraded,
            failed_at_stage, pipeline_stage_success_ratio,
            confidence, model, model_version,
            policy_override, policy_reason, triggered_policies,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        deployment.get("deployment_id"),
        deployment.get("author"),
        deployment.get("team"),
        deployment.get("files_changed"),
        deployment.get("test_coverage_pct"),
        deployment.get("environment"),
        result.get("risk_level"),
        result.get("reasoning"),
        result.get("suggested_action"),
        decision,
        None,   # actual_outcome -- unknown yet at decision time
        None,   # incident_severity -- unknown yet at decision time
        result.get("prompt_version"),
        1 if result.get("degraded") else 0,
        deployment.get("failed_at_stage"),
        deployment.get("pipeline_stage_success_ratio"),
        result.get("confidence"),
        result.get("model"),
        result.get("model_version"),
        1 if result.get("policy_override") else 0,
        result.get("policy_reason"),
        json.dumps(result.get("triggered_policies") or []),
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def update_outcome(deployment_id: str, actual_outcome: str, incident_severity: str = "none"):
    """
    Call this once the real outcome is known (success/fail), to close
    the feedback loop -- this is what lets the dashboard later show
    'predicted vs actual' accuracy.
    """
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_log
        SET actual_outcome = ?, incident_severity = ?
        WHERE deployment_id = ?
    """, (actual_outcome, incident_severity, deployment_id))
    conn.commit()
    conn.close()


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
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_log
        SET deployment_status = ?, health_check = ?, verification_time = ?
        WHERE deployment_id = ?
    """, (
        deployment_status,
        json.dumps(health_check) if health_check is not None else None,
        verification_time,
        deployment_id,
    ))
    conn.commit()
    rows_updated = cursor.rowcount
    conn.close()
    return rows_updated


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
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE audit_log
        SET recovery_status = ?, rollback_recommended = ?, recovery_reason = ?, recovery_timestamp = ?
        WHERE deployment_id = ?
    """, (
        recovery_status,
        1 if rollback_recommended else 0,
        recovery_reason,
        recovery_timestamp,
        deployment_id,
    ))
    conn.commit()
    rows_updated = cursor.rowcount
    conn.close()
    return rows_updated


def get_all_logs():
    """Returns every logged decision -- this is what the dashboard will call."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_log ORDER BY created_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # triggered_policies is stored as a JSON-encoded string (SQLite has no
    # array type); decode it back into a real list here so callers --
    # api.py's /history response and the dashboard -- see an actual JSON
    # array, not a string. Rows written before this column existed (or
    # where it's otherwise NULL) decode to an empty list rather than error.
    for row in rows:
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

    return rows


if __name__ == "__main__":
    # running this file directly just sets up the empty table, useful
    # for a first-time check that everything works
    init_db()
    print(f"Database ready: {DB_FILE}")
    print(f"Existing rows: {len(get_all_logs())}")
