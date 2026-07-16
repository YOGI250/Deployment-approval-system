"""
Notification service for deployment events.
"""

from utils import current_timestamp


def build_email(subject: str, message: str) -> dict:
    """
    Build an email notification payload.
    """

    return {
        "type": "email",
        "subject": subject,
        "message": message,
        "generated_at": current_timestamp()
    }


def build_teams_message(message: str) -> dict:
    """
    Build a Microsoft Teams notification payload.
    """

    return {
        "type": "teams",
        "message": message,
        "generated_at": current_timestamp()
    }


def notify(team: str, deployment_id: str, status: str) -> dict:
    """
    Simulate sending a deployment notification.
    """

    message = (
        f"Deployment {deployment_id} "
        f"for team '{team}' "
        f"is now '{status}'."
    )

    return {
        "email": build_email(
            "Deployment Status Update",
            message
        ),
        "teams": build_teams_message(message)
    }