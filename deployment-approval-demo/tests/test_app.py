from app import submit_deployment, approve_deployment, get_summary
from deployments import DEPLOYMENTS


def setup_function():
    DEPLOYMENTS.clear()


def test_submit_deployment():

    deployment = submit_deployment(
        team="payments",
        environment="production",
        version="v1.0.0",
        description="Initial deployment"
    )

    assert deployment["team"] == "payments"
    assert deployment["environment"] == "production"
    assert deployment["status"] == "Pending"


def test_approve_deployment():

    deployment = submit_deployment(
        "payments",
        "production",
        "v1.0.0",
        "Approval Test"
    )

    result = approve_deployment(deployment["deployment_id"])

    assert result is True


def test_get_summary():

    submit_deployment(
        "payments",
        "production",
        "v1.0.0",
        "Summary Test"
    )

    summary = get_summary()

    assert summary["total"] == 1
    assert summary["pending"] == 1