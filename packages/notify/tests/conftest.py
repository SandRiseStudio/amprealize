"""
Pytest configuration and fixtures for notify package tests.
"""

import pytest
from pathlib import Path


@pytest.fixture
def templates_dir():
    """Get the path to the package templates directory."""
    return Path(__file__).parent.parent / "src" / "notify" / "templates"


@pytest.fixture
def sample_context():
    """Sample context data for notification templates."""
    return {
        "org_name": "Acme Corporation",
        "inviter_name": "Alice Johnson",
        "invitee_name": "Bob Smith",
        "role": "member",
        "invite_url": "https://app.example.com/invite/abc123xyz",
        "token": "abc123xyz",
        "message": "Looking forward to working with you!",
        "project_name": "Project Alpha",
        "project_url": "https://app.example.com/projects/alpha",
        "update_type": "status_change",
        "update_message": "Project status changed to 'In Progress'",
        "alert_level": "warning",
        "alert_message": "System resources running low",
        "expires_in_days": 7,
    }


@pytest.fixture
def mock_smtp_server(mocker):
    """Mock SMTP server for email tests."""
    mock = mocker.patch("aiosmtplib.send")
    mock.return_value = ({}, "OK")
    return mock


@pytest.fixture
def mock_httpx_client(mocker):
    """Mock httpx async client for API-based providers."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.text = "ok"
    mock_response.json.return_value = {"ok": True}

    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_post.return_value = mock_response

    return mock_post
