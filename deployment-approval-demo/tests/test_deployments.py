from deployments import (
    create_deployment,
    update_status,
    deployment_summary,
    DEPLOYMENTS,
)


def setup_function():
    DEPLOYMENTS.clear()


def test_create_deployment():

    deployment = create_deployment(
        "payments",
        "production",
        "v1.0.0",
        "Deployment Test"
    )

    assert deployment["status"] == "Pending"


def test_update_status():

    deployment = create_deployment(
        "payments",
        "production",
        "v1.0.0",
        "Deployment Test"
    )

    result = update_status(
        deployment["deployment_id"],
        "Approved"
    )

    assert result is True
    assert deployment["status"] == "Approved"


def test_deployment_summary():

    create_deployment(
        "payments",
        "production",
        "v1.0.0",
        "Deployment Test"
    )

    summary = deployment_summary()

    assert summary["total"] == 1
    assert summary["pending"] == 1