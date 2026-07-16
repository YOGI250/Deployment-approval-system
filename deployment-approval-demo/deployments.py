"""
Business logic for the Deployment Management Service.
"""

from utils import (
    generate_deployment_id,
    current_timestamp,
)

from validation import (
    validate_environment,
    validate_team,
    validate_description,
    validate_version,
)

# In-memory deployment store
# (A real application would use a database.)
DEPLOYMENTS = []


def create_deployment(
    team: str,
    environment: str,
    version: str,
    description: str
) -> dict:
    """
    Create a deployment request.
    """

    if not validate_team(team):
        raise ValueError("Unsupported team.")

    if not validate_environment(environment):
        raise ValueError("Unsupported environment.")

    if not validate_version(version):
        raise ValueError("Invalid version.")

    if not validate_description(description):
        raise ValueError("Invalid description.")

    deployment = {
        "deployment_id": generate_deployment_id(),
        "team": team,
        "environment": environment,
        "version": version,
        "description": description,
        "status": "Pending",
        "created_at": current_timestamp()
    }

    DEPLOYMENTS.append(deployment)

    return deployment


def get_deployment(deployment_id: str):
    """
    Return a deployment by ID.
    """

    for deployment in DEPLOYMENTS:
        if deployment["deployment_id"] == deployment_id:
            return deployment

    return None


def update_status(
    deployment_id: str,
    status: str
) -> bool:
    """
    Update deployment status.
    """

    deployment = get_deployment(deployment_id)

    if deployment is None:
        return False

    deployment["status"] = status

    return True


def list_deployments():
    """
    Return all deployments.
    """

    return DEPLOYMENTS


def deployment_summary():
    """
    Return deployment statistics.
    """

    summary = {
        "total": len(DEPLOYMENTS),
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "deployed": 0,
        "cancelled": 0
    }

    for deployment in DEPLOYMENTS:

        status = deployment["status"].lower()

        if status == "pending":
            summary["pending"] += 1

        elif status == "approved":
            summary["approved"] += 1

        elif status == "rejected":
            summary["rejected"] += 1

        elif status == "deployed":
            summary["deployed"] += 1

        elif status == "cancelled":
            summary["cancelled"] += 1

    return summary