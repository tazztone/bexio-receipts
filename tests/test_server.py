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

# Use the same settings override as test_healthz
def get_test_settings():
    return Settings(
        env="development",
        bexio_api_token="dummy",
        review_password="test",
        ocr_engine="paddleocr",
        database_path=":memory:",
        review_dir="./review_queue_test"
    )

app.dependency_overrides[get_settings] = get_test_settings

def test_dashboard_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/", auth=("admin", "test_password"))
    assert response.status_code == 200

def test_stats_authorized(test_settings):
    app.dependency_overrides[get_settings] = lambda: test_settings
    response = client.get("/stats", auth=("admin", "test_password"))
    assert response.status_code == 200
