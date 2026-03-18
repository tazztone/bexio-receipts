import pytest
import os
from fastapi.testclient import TestClient
from bexio_receipts.server import app

client = TestClient(app)

def test_dashboard_unauthorized():
    response = client.get("/")
    assert response.status_code == 401

def test_dashboard_authorized():
    response = client.get("/", auth=("admin", "admin"))
    assert response.status_code == 200

def test_stats_authorized():
    response = client.get("/stats", auth=("admin", "admin"))
    assert response.status_code == 200
