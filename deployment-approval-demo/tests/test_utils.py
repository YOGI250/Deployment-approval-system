from utils import (
    generate_deployment_id,
    current_timestamp,
    success_response,
    error_response,
)


def test_generate_deployment_id():
    deployment_id = generate_deployment_id()

    assert deployment_id.startswith("DEP-")
    assert len(deployment_id) > 8


def test_current_timestamp():
    timestamp = current_timestamp()

    assert isinstance(timestamp, str)
    assert "T" in timestamp


def test_success_response():
    response = success_response(
        "Success",
        {"id": 1},
    )

    assert response["success"] is True
    assert response["message"] == "Success"
    assert response["data"]["id"] == 1


def test_error_response():
    response = error_response("Error")

    assert response["success"] is False
    assert response["message"] == "Error"