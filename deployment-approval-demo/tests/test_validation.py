from validation import (
    validate_environment,
    validate_team,
    validate_status,
    validate_description,
    validate_version,
)


def test_valid_environment():
    assert validate_environment("production") is True


def test_invalid_environment():
    assert validate_environment("mars") is False


def test_valid_team():
    assert validate_team("payments") is True


def test_invalid_team():
    assert validate_team("football") is False


def test_valid_status():
    assert validate_status("Approved") is True


def test_invalid_status():
    assert validate_status("Sleeping") is False


def test_valid_description():
    assert validate_description("Deployment release") is True


def test_invalid_description():
    assert validate_description("") is False


def test_valid_version():
    assert validate_version("v1.0") is True


def test_invalid_version():
    assert validate_version("1.0") is False