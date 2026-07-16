from notifications import (
    build_email,
    build_teams_message,
    notify,
)


def test_build_email():

    email = build_email(
        "Deployment",
        "Deployment Successful"
    )

    assert email["type"] == "email"
    assert email["subject"] == "Deployment"


def test_build_teams_message():

    message = build_teams_message(
        "Deployment Successful"
    )

    assert message["type"] == "teams"


def test_notify():

    response = notify(
        "payments",
        "DEP001",
        "Approved"
    )

    assert "email" in response
    assert "teams" in response