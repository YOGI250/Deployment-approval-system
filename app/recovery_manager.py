"""
recovery_manager.py

Purpose: DEV-010 -- Enterprise Deployment Recovery Framework.

IMPORTANT -- what this module is NOT: this project has no deployment
slots, no blue-green or canary setup, and no versioned deployment
artifacts. There is nothing here for code to mechanically roll back to,
so this module never claims to revert Azure App Service to a previous
version, and it never touches Azure at all.

What it does instead: turns the result of DEV-009's post-deployment
health check into a structured, auditable recovery recommendation --
what state the deployment is in, whether a human should roll back or
redeploy, and why. That decision (and the fact that it needs making)
gets recorded and surfaced instead of silently disappearing into a
pipeline log.
"""

import logging

logger = logging.getLogger("recovery_manager")

DEPLOYMENT_STATUS_DEPLOYED = "DEPLOYED"
DEPLOYMENT_STATUS_FAILED = "FAILED"

RECOVERY_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
RECOVERY_STATUS_REQUIRED = "RECOVERY_REQUIRED"

RECOMMENDED_ACTION_ROLLBACK = "Rollback to previous stable deployment or redeploy after fixing the issue."
RECOMMENDED_ACTION_NONE = "No action required."


def evaluate_recovery(deployment_id: str, health_status: str, verification_time: str) -> dict:
    """
    Decides whether a deployment needs recovery, based purely on the
    result of the post-deployment health check (GET /health, evaluated by
    POST /deployment-verification in api.py).

    health_status: "healthy" or "unhealthy" -- the same signal
        POST /deployment-verification derives from GET /health's HTTP
        status (200 -> healthy, anything else -> unhealthy).
    verification_time: ISO timestamp of when the health check ran --
        echoed back as this evaluation's timestamp, since a recovery
        decision is only ever as current as the check it's based on.

    No Azure rollback is performed or attempted here -- this only
    classifies the situation and recommends what a human should do next.
    """
    healthy = health_status == "healthy"

    if healthy:
        result = {
            "deployment_status": DEPLOYMENT_STATUS_DEPLOYED,
            "recovery_status": RECOVERY_STATUS_NOT_REQUIRED,
            "rollback_recommended": False,
            "recovery_reason": "Health check passed -- deployment is healthy and stable.",
            "recommended_action": RECOMMENDED_ACTION_NONE,
            "timestamp": verification_time,
        }
    else:
        result = {
            "deployment_status": DEPLOYMENT_STATUS_FAILED,
            "recovery_status": RECOVERY_STATUS_REQUIRED,
            "rollback_recommended": True,
            "recovery_reason": "Post-deployment health check failed -- the service did not report a healthy status after deployment.",
            "recommended_action": RECOMMENDED_ACTION_ROLLBACK,
            "timestamp": verification_time,
        }

    logger.info(
        "Recovery evaluation for deployment_id=%s: deployment_status=%s recovery_status=%s rollback_recommended=%s",
        deployment_id, result["deployment_status"], result["recovery_status"], result["rollback_recommended"],
    )
    return result
