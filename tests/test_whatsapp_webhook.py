"""Tests for WhatsApp webhook endpoints"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.config import settings

client = TestClient(app)


class TestWebhookVerification:
    """Tests for GET /webhook/whatsapp (webhook verification)"""
    
    def test_verify_webhook_success(self):
        """Test successful webhook verification"""
        # Set verify token for test
        with patch.object(settings, 'whatsapp_verify_token', 'test_verify_token_123'):
            response = client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "test_verify_token_123",
                    "hub.challenge": "1234567890"
                }
            )
            
            assert response.status_code == 200
            assert response.json() == "1234567890"
    
    def test_verify_webhook_invalid_token(self):
        """Test webhook verification with invalid token"""
        with patch.object(settings, 'whatsapp_verify_token', 'correct_token'):
            response = client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "1234567890"
                }
            )
            
            assert response.status_code == 403
            assert "Invalid verify token" in response.json()["detail"]
    
    def test_verify_webhook_invalid_mode(self):
        """Test webhook verification with invalid mode"""
        with patch.object(settings, 'whatsapp_verify_token', 'test_token'):
            response = client.get(
                "/webhook/whatsapp",
                params={
                    "hub.mode": "invalid_mode",
                    "hub.verify_token": "test_token",
                    "hub.challenge": "1234567890"
                }
            )
            
            assert response.status_code == 400
            assert "Invalid hub.mode" in response.json()["detail"]
    
    def test_verify_webhook_missing_parameters(self):
        """Test webhook verification with missing parameters"""
        response = client.get("/webhook/whatsapp")
        
        assert response.status_code == 400
        assert "Missing required parameters" in response.json()["detail"]


class TestWebhookReceive:
    """Tests for POST /webhook/whatsapp (receive messages)"""
    
    def test_receive_webhook_success(self):
        """Test receiving webhook with valid payload"""
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "123456789",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "6281234567890",
                                    "phone_number_id": "123456789"
                                },
                                "messages": [
                                    {
                                        "from": "6281234567890",
                                        "id": "wamid.test123",
                                        "timestamp": "1234567890",
                                        "type": "text",
                                        "text": {
                                            "body": "Hello"
                                        }
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        
        response = client.post("/webhook/whatsapp", json=payload)
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    
    def test_receive_webhook_empty_payload(self):
        """Test receiving webhook with empty payload"""
        response = client.post("/webhook/whatsapp", json={})
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
