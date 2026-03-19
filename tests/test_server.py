from fastapi.testclient import TestClient
from bexio_receipts.server import app, get_settings

client = TestClient(app)

def test_dashboard_unauthorized():
    # Ensure no auth
    response = client.get("/")
    assert response.status_code == 401

def test_dashboard_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/", auth=("admin", "test_password"))
    assert response.status_code == 200
    app.dependency_overrides.clear()

def test_stats_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/stats", auth=("admin", "test_password"))
    assert response.status_code == 200
    app.dependency_overrides.clear()
