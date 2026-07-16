"""
Deployment Management Service

A lightweight sample application used to simulate
a real project for the AI Deployment Approval Assistant.
"""

from deployments import (
    create_deployment,
    get_deployment,
    update_status,
    list_deployments,
    deployment_summary,
)

from notifications import notify


def submit_deployment(
    team: str,
    environment: str,
    version: str,
    description: str,
) -> dict:
    """
    Submit a deployment request.
    """

    deployment = create_deployment(
        team,
        environment,
        version,
        description,
    )

    notify(
        deployment["team"],
        deployment["deployment_id"],
        deployment["status"],
    )

    return deployment


def approve_deployment(deployment_id: str) -> bool:
    """
    Approve a deployment.
    """
    return update_status(deployment_id, "Approved")


def reject_deployment(deployment_id: str) -> bool:
    """
    Reject a deployment.
    """
    return update_status(deployment_id, "Rejected")


def deploy_application(deployment_id: str) -> bool:
    """
    Mark deployment as deployed.
    """
    return update_status(deployment_id, "Deployed")


def get_summary():
    """
    Return deployment statistics.
    """
    return deployment_summary()


if __name__ == "__main__":

    deployment = submit_deployment(
        team="payments",
        environment="production",
        version="v1.0.0",
        description="Release payment service improvements",
    )

    print("Deployment Created")
    print(deployment)

    print("\nSummary")
    print(get_summary())