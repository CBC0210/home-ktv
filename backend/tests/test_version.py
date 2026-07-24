import pytest
from fastapi.testclient import TestClient

from ktv_pipeline.config import settings
from main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "ktv-backend"
    assert data["version"] == settings.version
    assert data["db"] == "connected"


def test_health_db_field():
    response = client.get("/health")
    assert "db" in response.json()


def test_version_returns_200():
    response = client.get("/version")
    assert response.status_code == 200


def test_version_fields():
    data = client.get("/version").json()
    assert data["app"] == "ktv-backend"
    assert "version" in data
    assert "settings" in data
    assert "gpu" in data
    assert "db" in data


def test_version_settings():
    data = client.get("/version").json()
    assert data["settings"]["whisperx_model"] == settings.whisperx_model
    assert data["settings"]["demucs_model"] == settings.demucs_model
    assert data["settings"]["enable_gpu"] == settings.enable_gpu


def test_version_db():
    data = client.get("/version").json()
    assert data["db"]["connected"] is True
    assert data["db"]["path"] == str(settings.db_path)


def test_version_gpu_shape():
    data = client.get("/version").json()
    gpu = data["gpu"]
    assert "available" in gpu
    # if GPU is available, expect memory fields
    if gpu["available"]:
        assert "name" in gpu
        assert "memory_total_gb" in gpu


def test_root_returns_ok():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"