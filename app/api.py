"""
api.py

Purpose: turns risk_scorer.py's score_deployment() function into a real,
running API -- something Azure DevOps (or anything else) can send a
request to and get a risk decision back.

This is the "translator" piece: Azure DevOps can't call a Python function
directly, but it CAN send a web request to a URL. This file creates that URL.

Install first:
    pip install fastapi uvicorn --break-system-packages

Run it:
    uvicorn api:app --reload

Then open http://127.0.0.1:8000/docs in your browser -- FastAPI
automatically builds an interactive test page for you. You can send a
test request right from that page, no separate tool needed.
"""

import os
import csv
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Any
from risk_scorer import score_deployment, calculate_author_success_rate, HISTORY_CSV_PATH
from audit_log import (
    init_db, log_decision, get_all_logs, update_outcome, check_connection,
    update_verification, update_recovery,
)
from email_notify import notify_decision, notify_outcome, notify_verification_failure, notify_recovery_required
from ml.predictor import _get_model, MODEL_NAME, MODEL_VERSION
import recovery_manager
from model_info import get_model_info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api")

app = FastAPI(title="Deployment Risk Assistant")

# creates the database file/table on startup if it doesn't already exist
init_db()

# --- Authentication -----------------------------------------------------
# A real API shouldn't be callable by anyone who finds the URL. This is a
# simple shared-secret check -- the caller (Azure DevOps, or you testing
# locally) must send a matching header. Set API_KEY in your .env; if it's
# not set, auth is skipped (useful for quick local testing), but a
# warning is logged so this can't accidentally ship unprotected.
API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    logger.warning("API_KEY is not set -- /predict and /outcome are UNAUTHENTICATED. Set API_KEY in .env before real use.")


def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return True


class DeploymentRequest(BaseModel):
    """
    This defines exactly what data a caller must send us. FastAPI uses
    this to validate incoming requests automatically -- if someone sends
    a request missing a field, or with the wrong type, it rejects it
    with a clear error before our code even runs.
    """
    deployment_id: str
    author: str
    team: str
    files_changed: int
    lines_changed: int
    test_coverage_pct: float
    tests_failed: int
    environment: str
    day_of_week: str
    hour: int
    changed_files: List[str] = []  # optional real file paths -- enables criticality detection
    failed_at_stage: Optional[str] = None  # "build", "test", "deploy", or None if nothing failed
    pipeline_stage_success_ratio: Optional[float] = None  # this pipeline's historical stage success rate, 0-1


def get_combined_history() -> list:
    """
    Combines the synthetic 'past company history' CSV with the REAL history
    now sitting in our own audit log -- so the AI's 'similar past
    deployments' and 'author success rate' lookups start reflecting genuine
    activity from real people (like Dharani) as soon as outcomes get
    recorded, instead of only ever seeing the fictional starter data.

    Only real audit log rows with a known actual_outcome are included --
    a deployment we haven't heard the real result of yet can't be counted
    as a success or a failure.
    """
    history_rows = []
    try:
        with open(HISTORY_CSV_PATH) as f:
            history_rows.extend(csv.DictReader(f))
    except FileNotFoundError:
        logger.warning("deployment_history.csv not found -- proceeding with real audit log data only")

    real_rows = get_all_logs()
    for row in real_rows:
        if row.get("actual_outcome"):  # only include rows with a known real outcome
            history_rows.append({
                "author": row.get("author"),
                "files_changed": row.get("files_changed"),
                "outcome": row.get("actual_outcome"),
                "incident_severity": row.get("incident_severity"),
            })

    return history_rows


@app.get("/")
def health_check():
    """A simple 'is this thing alive' endpoint -- useful for quick testing."""
    return {"status": "ok", "message": "Deployment Risk Assistant is running"}


@app.get("/health")
def health():
    """
    DEV-009: enterprise deployment verification endpoint. Called by the
    Azure Pipeline ~20 seconds after a deploy to decide whether the
    deployment succeeded. Unauthenticated on purpose, matching "/" above
    -- health/liveness probes (pipelines, uptime monitors, load
    balancers) shouldn't need a secret just to ask "are you up".

    Checks three independent things and never lets one crash the others:
      - FastAPI is running       (true simply by virtue of this handler executing)
      - the RandomForest model is loaded and usable
      - the audit database is reachable

    Returns HTTP 200 when everything checks out, HTTP 503 otherwise --
    that status code, not the JSON body, is what the pipeline's
    "if HTTP 200 -> success, otherwise -> failed" logic keys off.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    model_loaded = False
    try:
        _get_model()
        model_loaded = True
    except Exception as e:
        logger.error("Health check: model failed to load: %s", e)

    database_ok = check_connection()
    if not database_ok:
        logger.error("Health check: audit database is not reachable")

    healthy = model_loaded and database_ok
    body = {
        "status": "healthy" if healthy else "unhealthy",
        "model": MODEL_NAME if model_loaded else "unavailable",
        "version": MODEL_VERSION if model_loaded else None,
        "database": "connected" if database_ok else "unreachable",
        "timestamp": timestamp,
    }

    logger.info("Health check: status=%s model=%s database=%s", body["status"], body["model"], body["database"])

    return JSONResponse(status_code=200 if healthy else 503, content=body)


@app.get("/model-info")
def model_info():
    """
    IMP-002: real, non-fabricated facts about the currently deployed ML
    model, for the dashboard's Model Information panel. Unauthenticated,
    matching "/" and "/health" -- this is model metadata, not deployment
    data. Every field is read live from the model artifact, an optional
    metadata file, or the filesystem -- "N/A" when none of those have it.
    See model_info.py for exactly what each field comes from.
    """
    return get_model_info()


@app.post("/predict")
def predict(deployment: DeploymentRequest, authorized: bool = Depends(verify_api_key)):
    """
    The main endpoint. Azure DevOps's approval check will call this URL
    with deployment details, and we respond with a risk decision.
    """
    logger.info("Received /predict for deployment_id=%s author=%s", deployment.deployment_id, deployment.author)
    deployment_dict = deployment.model_dump()

    # combines the fake starter history with your REAL audit log data --
    # used both for the author success rate (existing) and for RAG
    # grounding: finding similar past deployments, including real ones
    # from this same person if they've deployed before
    history_rows = get_combined_history()
    deployment_dict["author_recent_success_rate"] = calculate_author_success_rate(
        deployment.author, history_rows
    )

    result = score_deployment(deployment_dict, history_rows=history_rows)

    if result.get("degraded"):
        logger.error("Explanation generation degraded for deployment_id=%s -- AI service was unreachable (risk_level/decision are unaffected, from the ML model)", deployment.deployment_id)
    # Policy override events are logged in risk_scorer.score_deployment(),
    # the one place that has both the original ML prediction and the final
    # risk in scope together.

    # the business decision (approve/delay/reject) comes from
    # decision_engine.py via score_deployment -- not recomputed here, so
    # this mapping lives in exactly one place
    action = result["decision"]

    # write this decision to the audit log -- this is the piece that makes
    # every decision reviewable later, instead of vanishing after the reply
    log_decision(deployment_dict, result, action)
    logger.info("Decision for deployment_id=%s: risk=%s confidence=%.2f action=%s model=%s prompt_version=%s",
                deployment.deployment_id, result["risk_level"], result.get("confidence", 0.0), action,
                result.get("model"), result.get("prompt_version"))

    # email the decision -- satisfies the notifications requirement
    notify_decision(
        deployment_id=deployment.deployment_id,
        risk_level=result["risk_level"],
        reasoning=result["reasoning"],
        suggested_action=result["suggested_action"],
        decision=action,
    )

    return {
        "deployment_id": deployment.deployment_id,
        "risk_level": result["risk_level"],
        "confidence": result.get("confidence"),
        "decision": action,
        "reasoning": result["reasoning"],
        "suggested_action": result["suggested_action"],
        "model": result.get("model"),
        "model_version": result.get("model_version"),
        "prompt_version": result.get("prompt_version"),
        "degraded": result.get("degraded", False),
        "policy_override": result.get("policy_override", False),
        "policy_reason": result.get("policy_reason"),
        "triggered_policies": result.get("triggered_policies", []),
    }


@app.get("/history")
def history(authorized: bool = Depends(verify_api_key)):
    """Returns every logged decision so far -- the dashboard will use this same data."""
    return get_all_logs()


class OutcomeRequest(BaseModel):
    deployment_id: str
    actual_outcome: str   # "success" or "fail"
    incident_severity: str = "none"   # "none", "minor", or "major"


@app.post("/outcome")
def report_outcome(outcome: OutcomeRequest, authorized: bool = Depends(verify_api_key)):
    """
    Call this once a deployment's real result is known -- this is the
    feedback loop piece from the brief. It updates the audit log row
    and sends a follow-up email, closing the loop between prediction
    and reality.
    """
    logger.info("Recording outcome for deployment_id=%s: %s", outcome.deployment_id, outcome.actual_outcome)
    update_outcome(
        deployment_id=outcome.deployment_id,
        actual_outcome=outcome.actual_outcome,
        incident_severity=outcome.incident_severity,
    )

    notify_outcome(
        deployment_id=outcome.deployment_id,
        actual_outcome=outcome.actual_outcome,
        incident_severity=outcome.incident_severity,
    )

    return {"status": "outcome recorded", "deployment_id": outcome.deployment_id}


class DeploymentVerificationRequest(BaseModel):
    """
    DEV-009: what the Azure Pipeline reports back after it calls
    GET /health itself, ~20 seconds post-deploy. The pipeline (not this
    API) does the waiting and the HTTP call to /health -- this endpoint's
    only job is to persist that result against the right audit log row
    and fire the failure email, mirroring how /outcome closes the loop
    for real-world results.
    """
    deployment_id: str
    health_status: str            # "healthy" or "unhealthy", as observed by the pipeline
    http_status_code: int         # the raw HTTP status GET /health returned
    health_check: Optional[Any] = None  # the /health response body, or a raw fallback if it wasn't JSON


@app.post("/deployment-verification")
def record_deployment_verification(
    verification: DeploymentVerificationRequest, authorized: bool = Depends(verify_api_key)
):
    """
    Records a post-deployment health verification result in the audit
    log (deployment_status, health_check, verification_time) and, if the
    deployment came back unhealthy, sends a failure notification email.

    DEV-010: also runs the result through recovery_manager to decide
    whether this deployment needs recovery attention, persists that
    recommendation (recovery_status, rollback_recommended,
    recovery_reason, recovery_timestamp), and emails a separate
    "Deployment Recovery Required" notice when it does. No Azure
    rollback happens anywhere in this flow -- recovery_manager only
    classifies the situation and recommends a next step for a human.
    """
    deployment_status = "success" if verification.http_status_code == 200 else "failed"
    verification_time = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Deployment verification for deployment_id=%s: deployment_status=%s health_status=%s http_status_code=%s",
        verification.deployment_id, deployment_status, verification.health_status, verification.http_status_code,
    )

    rows_updated = update_verification(
        deployment_id=verification.deployment_id,
        deployment_status=deployment_status,
        health_check=verification.health_check,
        verification_time=verification_time,
    )
    if not rows_updated:
        logger.warning(
            "Deployment verification recorded for unknown deployment_id=%s -- no matching audit log row to attach it to",
            verification.deployment_id,
        )

    if deployment_status != "success":
        notify_verification_failure(
            deployment_id=verification.deployment_id,
            health_check=verification.health_check,
            http_status_code=verification.http_status_code,
        )

    recovery = recovery_manager.evaluate_recovery(
        deployment_id=verification.deployment_id,
        health_status="healthy" if deployment_status == "success" else "unhealthy",
        verification_time=verification_time,
    )

    update_recovery(
        deployment_id=verification.deployment_id,
        recovery_status=recovery["recovery_status"],
        rollback_recommended=recovery["rollback_recommended"],
        recovery_reason=recovery["recovery_reason"],
        recovery_timestamp=recovery["timestamp"],
    )

    if recovery["rollback_recommended"]:
        notify_recovery_required(
            deployment_id=verification.deployment_id,
            recovery_reason=recovery["recovery_reason"],
            rollback_recommended=recovery["rollback_recommended"],
            recommended_action=recovery["recommended_action"],
            health_check=verification.health_check,
        )

    return {
        "status": "verification recorded",
        "deployment_id": verification.deployment_id,
        "deployment_status": deployment_status,
        "verification_time": verification_time,
        "recovery_status": recovery["recovery_status"],
        "rollback_recommended": recovery["rollback_recommended"],
        "recovery_reason": recovery["recovery_reason"],
        "recommended_action": recovery["recommended_action"],
    }
