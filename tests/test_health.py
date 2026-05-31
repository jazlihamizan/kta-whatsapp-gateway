"""Tests for health check endpoint"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    """Test health check endpoint returns 200 OK"""
    response = client.get("/health")
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "KTA WhatsApp Gateway"
    assert "version" in data


def test_health_check_structure():
    """Test health check response has correct structure"""
    response = client.get("/health")
    
    data = response.json()
    assert isinstance(data, dict)
    assert "status" in data
    assert "service" in data
    assert "version" in data
