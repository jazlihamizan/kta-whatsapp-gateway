"""Tests for WhatsApp webhook endpoints"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

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
            assert response.text == "1234567890"

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


class TestWebhookReceiveMediaTypes:
    """Tests for receiving non-text WhatsApp message types."""

    def _make_payload(self, message_type: str, message: dict) -> dict:
        return {
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
                                    "phone_number_id": "123456789",
                                },
                                "contacts": [
                                    {
                                        "wa_id": "6281234567890",
                                        "profile": {"name": "Test User"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "6281234567890",
                                        "id": "wamid.test_media",
                                        "timestamp": "1234567890",
                                        "type": message_type,
                                        **message,
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

    def test_receive_image(self):
        """Test receiving image message - extracts media metadata."""
        payload = self._make_payload("image", {
            "image": {
                "id": "MEDIA_IMG_123",
                "mime_type": "image/jpeg",
                "sha256": "abc123",
                "caption": "Foto KTP saya",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_document(self):
        """Test receiving document message - extracts media metadata."""
        payload = self._make_payload("document", {
            "document": {
                "id": "MEDIA_DOC_456",
                "mime_type": "application/pdf",
                "sha256": "def456",
                "filename": "ktp_scan.pdf",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_audio(self):
        """Test receiving audio message - extracts media metadata."""
        payload = self._make_payload("audio", {
            "audio": {
                "id": "MEDIA_AUD_789",
                "mime_type": "audio/ogg",
                "sha256": "ghi789",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_video(self):
        """Test receiving video message - extracts media metadata."""
        payload = self._make_payload("video", {
            "video": {
                "id": "MEDIA_VID_012",
                "mime_type": "video/mp4",
                "sha256": "jkl012",
                "caption": "Video selfie",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_location(self):
        """Test receiving location message - extracts coordinates."""
        payload = self._make_payload("location", {
            "location": {
                "latitude": -6.2088,
                "longitude": 106.8456,
                "name": "Gedung Partai",
                "address": "Jl. Contoh No. 1",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_receive_sticker(self):
        """Test receiving sticker message."""
        payload = self._make_payload("sticker", {
            "sticker": {
                "id": "MEDIA_STK_345",
                "mime_type": "image/webp",
                "sha256": "mno345",
            }
        })
        response = client.post("/webhook/whatsapp", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSendMessageReplyTo:
    """Tests for /send-message with reply_to threading."""

    def test_send_message_without_reply_to(self):
        """send_message without reply_to should call WhatsAppService with reply_to=None."""
        with patch("app.routes.whatsapp.whatsapp_service.send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"messages": [{"id": "wamid.reply1"}]}
            response = client.post("/send-message", json={
                "to": "6281234567890",
                "message": "Hello!",
            })
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            mock_send.assert_called_once_with("6281234567890", "Hello!", reply_to=None)

    def test_send_message_with_reply_to(self):
        """send_message with reply_to should pass it through to WhatsAppService."""
        with patch("app.routes.whatsapp.whatsapp_service.send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"messages": [{"id": "wamid.reply2"}]}
            response = client.post("/send-message", json={
                "to": "6281234567890",
                "message": "Hello back!",
                "reply_to": "wamid.original123",
            })
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            mock_send.assert_called_once_with("6281234567890", "Hello back!", reply_to="wamid.original123")
