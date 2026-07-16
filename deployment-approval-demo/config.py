"""
Application configuration.

This module stores configuration values used across the
Deployment Management Service.
"""

SUPPORTED_ENVIRONMENTS = [
    "development",
    "testing",
    "staging",
    "production"
]

SUPPORTED_TEAMS = [
    "payments",
    "checkout",
    "search",
    "notifications",
    "orders",
    "platform"
]

SUPPORTED_STATUS = [
    "Pending",
    "Approved",
    "Rejected",
    "Deployed",
    "Cancelled"
]

MAX_DESCRIPTION_LENGTH = 500

DEFAULT_TIMEOUT_SECONDS = 30

MAX_DEPLOYMENT_RETRIES = 3