import pytest
import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def settings():
    return get_settings()


def test_webhook_handshake(client):
    """Test Asana webhook handshake request."""
    response = client.post(
        "/webhook/asana",
        headers={"X-Hook-Secret": "test-secret"},
    )
    assert response.status_code == 200
    assert response.json()["X-Hook-Secret"] == "test-secret"


def test_webhook_invalid_signature(client, settings):
    """Test webhook with invalid HMAC signature."""
    payload = {"id": "test-event", "events": []}
    payload_json = json.dumps(payload)

    response = client.post(
        "/webhook/asana",
        content=payload_json,
        headers={
            "Content-Type": "application/json",
            "X-Hook-Signature": "invalid-signature",
        },
    )
    assert response.status_code == 401


def test_webhook_valid_signature(client, settings):
    """Test webhook with valid HMAC signature."""
    payload = {"id": "test-event", "events": []}
    payload_json = json.dumps(payload)

    signature = hmac.new(
        settings.asana_webhook_secret.encode(),
        payload_json.encode(),
        hashlib.sha256,
    ).hexdigest()

    response = client.post(
        "/webhook/asana",
        content=payload_json,
        headers={
            "Content-Type": "application/json",
            "X-Hook-Signature": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"


def test_webhook_returns_200_immediately(client, settings):
    """Test that webhook returns 200 before processing."""
    payload = {"id": "test-event", "events": []}
    payload_json = json.dumps(payload)

    signature = hmac.new(
        settings.asana_webhook_secret.encode(),
        payload_json.encode(),
        hashlib.sha256,
    ).hexdigest()

    response = client.post(
        "/webhook/asana",
        content=payload_json,
        headers={
            "Content-Type": "application/json",
            "X-Hook-Signature": signature,
        },
    )
    # Should return 200 immediately, not wait for processing
    assert response.status_code == 200
