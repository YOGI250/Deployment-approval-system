"""
Validation functions for the Deployment Management Service.
"""

from config import (
    SUPPORTED_ENVIRONMENTS,
    SUPPORTED_TEAMS,
    SUPPORTED_STATUS,
    MAX_DESCRIPTION_LENGTH,
)


def validate_environment(environment: str) -> bool:
    """
    Check whether the deployment environment is supported.
    """
    return environment.lower() in SUPPORTED_ENVIRONMENTS


def validate_team(team: str) -> bool:
    """
    Check whether the deployment team is registered.
    """
    return team.lower() in SUPPORTED_TEAMS


def validate_status(status: str) -> bool:
    """
    Validate deployment status.
    """
    return status.title() in SUPPORTED_STATUS


def validate_description(description: str) -> bool:
    """
    Ensure deployment description is not empty
    and does not exceed the maximum length.
    """
    return 0 < len(description) <= MAX_DESCRIPTION_LENGTH


def validate_version(version: str) -> bool:
    """
    Very simple version validation.

    Examples:
        v1.0
        v2.3.1
    """
    return version.startswith("v")