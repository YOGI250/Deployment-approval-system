"""
models.py

Purpose: the SQLAlchemy ORM model for the audit_log table. Column names
and types mirror the SQLite schema this replaces (see the old
audit_log.py CREATE TABLE) exactly, so existing data and existing
callers (api.py, dashboard.py, accuracy_metrics.py) see no difference.

Boolean-ish columns (degraded, policy_override, rollback_recommended)
stay Integer (0/1) rather than Boolean -- the API's JSON responses have
always serialized these as 0/1, and switching to Boolean would silently
change that to true/false, which the brief says not to do.

triggered_policies and health_check stay Text (JSON-encoded strings,
handled manually in audit_log.py) rather than a native JSON column, so
the existing json.dumps/json.loads round-trip in audit_log.py needs no
changes.

created_at stays Text (an ISO 8601 string written by datetime.now().isoformat()),
not a native Timestamp, so get_all_logs() keeps returning a plain str
exactly as it did against SQLite -- no format change for the dashboard
or /history's JSON.
"""

from sqlalchemy import Column, Integer, Float, Text
from database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    deployment_id = Column(Text)
    author = Column(Text)
    team = Column(Text)
    files_changed = Column(Integer)
    lines_changed = Column(Integer)
    test_coverage_pct = Column(Float)
    tests_failed = Column(Integer)
    changed_files = Column(Text)
    day_of_week = Column(Text)
    hour = Column(Integer)
    environment = Column(Text)
    risk_level = Column(Text)
    reasoning = Column(Text)
    suggested_action = Column(Text)
    decision = Column(Text)
    actual_outcome = Column(Text)
    incident_severity = Column(Text)
    prompt_version = Column(Text)
    degraded = Column(Integer, default=0)
    failed_at_stage = Column(Text)
    pipeline_stage_success_ratio = Column(Float)
    confidence = Column(Float)
    model = Column(Text)
    model_version = Column(Text)
    policy_override = Column(Integer, default=0)
    policy_reason = Column(Text)
    triggered_policies = Column(Text)
    threshold_override = Column(Integer, default=0)
    threshold_reason = Column(Text)
    triggered_thresholds = Column(Text)
    deployment_status = Column(Text)
    health_check = Column(Text)
    verification_time = Column(Text)
    recovery_status = Column(Text)
    rollback_recommended = Column(Integer, default=0)
    recovery_reason = Column(Text)
    recovery_timestamp = Column(Text)
    created_at = Column(Text)
