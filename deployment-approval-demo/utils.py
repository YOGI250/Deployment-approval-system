"""
Utility functions for the Deployment Management Service.
"""

from datetime import datetime
import uuid


def generate_deployment_id() -> str:
    """
    Generate a unique deployment identifier.
    Example: DEP-3F7A2B91
    """
    return f"DEP-{uuid.uuid4().hex[:8].upper()}"


def current_timestamp() -> str:
    """
    Return the current UTC timestamp in ISO 8601 format.
    """
    return datetime.utcnow().isoformat() + "Z"


def success_response(message: str, data: dict | None = None) -> dict:
    """
    Build a standard success response.
    """
    return {
        "success": True,
        "message": message,
        "data": data or {}
    }


def error_response(message: str) -> dict:
    """
    Build a standard error response.
    """
    return {
        "success": False,
        "message": message
    }