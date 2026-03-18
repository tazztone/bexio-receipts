from fastapi.testclient import TestClient
from bexio_receipts.server import app, get_settings

client = TestClient(app)

def override_get_settings():
    from bexio_receipts.config import Settings
    return Settings(
        bexio_api_token="test_token",
        review_password="admin"
    )

app.dependency_overrides[get_settings] = override_get_settings

def test_dashboard_unauthorized():
    response = client.get("/")
    assert response.status_code == 401

def test_dashboard_authorized():
    response = client.get("/", auth=("admin", "admin"))
    assert response.status_code == 200

def test_stats_authorized():
    response = client.get("/stats", auth=("admin", "admin"))
    assert response.status_code == 200
