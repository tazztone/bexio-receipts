import json
from fastapi.testclient import TestClient
from bexio_receipts.server import app, get_settings

client = TestClient(app)

def test_get_image_canonicalization_failure(test_settings, tmp_path):
    # Setup review_dir and a malicious JSON
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    
    test_settings.review_dir = str(review_dir)
    test_settings.inbox_path = str(inbox_dir)
    
    # Secret file outside allowed roots
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("sensitive data")
    
    review_id = "malicious"
    review_json = review_dir / f"{review_id}.json"
    with open(review_json, "w") as f:
        json.dump({"original_file": str(secret_file)}, f)
    
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    response = client.get(f"/image/{review_id}", auth=("admin", "test_password"))
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"
    
    app.dependency_overrides.clear()

def test_get_image_canonicalization_success(test_settings, tmp_path):
    # Setup review_dir and a valid JSON
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()
    
    test_settings.review_dir = str(review_dir)
    test_settings.inbox_path = str(inbox_dir)
    
    # Valid file inside inbox
    valid_file = inbox_dir / "receipt.jpg"
    valid_file.write_text("fake image data")
    
    review_id = "valid"
    review_json = review_dir / f"{review_id}.json"
    with open(review_json, "w") as f:
        json.dump({"original_file": str(valid_file)}, f)
    
    app.dependency_overrides[get_settings] = lambda: test_settings
    
    response = client.get(f"/image/{review_id}", auth=("admin", "test_password"))
    assert response.status_code == 200
    assert response.text == "fake image data"
    
    app.dependency_overrides.clear()
