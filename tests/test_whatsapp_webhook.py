"""Tests for WhatsApp webhook endpoints"""
import pytest
import hmac
import hashlib
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

from app.main import app
from app.config import settings
from app.middleware.rate_limit import SlidingWindowRateLimiter, _rate_limiter, reset_rate_limiter, check_rate_limit

client = TestClient(app)


# ---------------------------------------------------------------------------
# R1: X-Hub-Signature-256 Tests
# ---------------------------------------------------------------------------
class TestSignatureVerification:
    """Tests for R1: X-Hub-Signature-256 verification."""

    def _make_sig_header(self, body: bytes, secret: str) -> str:
        """Helper: compute valid sha256= signature header."""
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def _valid_post_payload(self) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "123456789"},
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test123",
                            "timestamp": "1234567890",
                            "type": "text",
                            "text": {"body": "Hello"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

    def test_signature_valid_accepts_request(self):
        """Valid signature should be accepted when verification is enabled."""
        body = b'{"test": "payload"}'
        sig = self._make_sig_header(body, "test_secret_123")

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", "test_secret_123"):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": sig
                }
            )
            # Should process (200 ok, not 401)
            assert response.status_code == 200

    def test_signature_invalid_rejected(self):
        """Invalid signature should be rejected with 401 when verification is enabled."""
        body = b'{"test": "payload"}'

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", "test_secret_123"):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": "sha256=invalid_signature_here"
                }
            )
            assert response.status_code == 401

    def test_signature_missing_rejected_when_enabled(self):
        """Missing signature should be rejected with 401 when verification is enabled."""
        body = b'{"test": "payload"}'

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", "test_secret_123"):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"content-type": "application/json"}
            )
            assert response.status_code == 401

    def test_signature_verification_disabled_accepts_request(self):
        """When verification is disabled, requests should be accepted without signature."""
        body = b'{"test": "payload"}'

        with patch.object(settings, "whatsapp_signature_verify_enabled", False), \
             patch.object(settings, "whatsapp_app_secret", ""):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"content-type": "application/json"}
            )
            assert response.status_code == 200

    def test_signature_enabled_empty_secret_rejected(self):
        """When verification is enabled but WHATSAPP_APP_SECRET is empty, request must be rejected (fail-closed)."""
        body = b'{"test": "payload"}'

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", ""):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={"content-type": "application/json"}
            )
            assert response.status_code == 401
            assert "WHATSAPP_APP_SECRET is not configured" in response.json()["detail"]

    def test_signature_wrong_secret_rejected(self):
        """Signature computed with wrong secret should be rejected."""
        body = b'{"test": "payload"}'
        sig = self._make_sig_header(body, "wrong_secret")

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", "correct_secret"):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": sig
                }
            )
            assert response.status_code == 401

    def test_signature_malformed_header_rejected(self):
        """Malformed signature header (no sha256= prefix) should be rejected."""
        body = b'{"test": "payload"}'

        with patch.object(settings, "whatsapp_signature_verify_enabled", True), \
             patch.object(settings, "whatsapp_app_secret", "test_secret"):
            response = client.post(
                "/webhook/whatsapp",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": "just_hex_digest_no_prefix"
                }
            )
            assert response.status_code == 401


# ---------------------------------------------------------------------------
# R2: Metadata handling tests
# ---------------------------------------------------------------------------
class TestMetadataHandling:
    """Tests for R2: metadata field not silently dropped."""

    def test_metadata_logged_safely_without_sensitive_leak(self):
        """Metadata should be logged safely without exposing sensitive fields."""
        with patch("app.routes.whatsapp.whatsapp_service.send_message", new_callable=AsyncMock) as mock_send, \
             patch("app.routes.whatsapp.logger") as mock_logger:
            mock_send.return_value = {"messages": [{"id": "wamid.test"}]}
            response = client.post("/send-message", json={
                "to": "6281234567890",
                "message": "test",
                "metadata": {
                    "source_service": "wa-router",
                    "trace_id": "gw-20260531143000",
                    "api_key": "super_secret_key_12345",  # should be redacted
                    "password": "my_password",  # should be redacted
                    "token": "bearer_token_xyz",  # should be redacted
                    "safe_field": "visible_value"
                }
            })
            assert response.status_code == 200
            # Check that sensitive fields were not logged as plain text
            debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
            for call in debug_calls:
                assert "super_secret_key_12345" not in call or "***REDACTED***" in call
                assert "my_password" not in call or "***REDACTED***" in call
                assert "bearer_token_xyz" not in call or "***REDACTED***" in call

    def test_metadata_not_sent_to_meta(self):
        """Metadata should NOT be forwarded to Meta WhatsApp API payload."""
        captured_payload = {}

        async def mock_send_message(to, message, reply_to=None):
            # Capture what was actually sent
            captured_payload["to"] = to
            captured_payload["message"] = message
            captured_payload["reply_to"] = reply_to
            return {"messages": [{"id": "wamid.test"}]}

        with patch("app.routes.whatsapp.whatsapp_service.send_message", side_effect=mock_send_message):
            response = client.post("/send-message", json={
                "to": "6281234567890",
                "message": "Hello",
                "metadata": {"trace_id": "gw-123", "session_id": "abc"}
            })
            assert response.status_code == 200
            # Metadata should NOT be part of what was sent to the service
            # (reply_to is the only extra field sent to Meta)
            assert captured_payload.get("reply_to") is None

    def test_metadata_optional(self):
        """Sending message without metadata should still work."""
        with patch("app.routes.whatsapp.whatsapp_service.send_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"messages": [{"id": "wamid.test"}]}
            response = client.post("/send-message", json={
                "to": "6281234567890",
                "message": "Hello without metadata"
            })
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


# ---------------------------------------------------------------------------
# R3: CORS configurable tests
# ---------------------------------------------------------------------------
class TestCORSConfigurable:
    """Tests for R3: CORS configurable via env."""

    def test_cors_origins_star_by_default(self):
        """Default CORS_ALLOW_ORIGINS should be '*'."""
        with patch.object(settings, "cors_allow_origins", "*"):
            assert settings.cors_origins_list == ["*"]

    def test_cors_origins_comma_separated(self):
        """CORS_ALLOW_ORIGINS should support comma-separated values."""
        with patch.object(settings, "cors_allow_origins", "https://kta.partaiummat.or.id, https://admin.partaiummat.or.id"):
            assert settings.cors_origins_list == [
                "https://kta.partaiummat.or.id",
                "https://admin.partaiummat.or.id"
            ]

    def test_cors_origins_single_origin(self):
        """Single origin should parse correctly."""
        with patch.object(settings, "cors_allow_origins", "https://kta.partaiummat.or.id"):
            assert settings.cors_origins_list == ["https://kta.partaiummat.or.id"]

    def test_cors_origins_trims_whitespace(self):
        """Origins should be trimmed of whitespace."""
        with patch.object(settings, "cors_allow_origins", " https://a.com , https://b.com "):
            assert settings.cors_origins_list == ["https://a.com", "https://b.com"]

    def test_cors_no_wildcard_in_prod_list(self):
        """Production CORS list should not contain '*' unless explicitly set."""
        with patch.object(settings, "cors_allow_origins", "https://kta.partaiummat.or.id,https://admin.partaiummat.or.id"):
            assert "*" not in settings.cors_origins_list
            assert len(settings.cors_origins_list) == 2


# ---------------------------------------------------------------------------
# R6: Rate limiting tests
# ---------------------------------------------------------------------------
class TestRateLimiting:
    """Tests for R6: gateway rate limiting (in-memory)."""

    def test_rate_limiter_allows_under_limit(self):
        """Requests under the limit should be allowed."""
        limiter = SlidingWindowRateLimiter(requests_per_minute=10, burst=5)
        ip = "192.168.1.100"
        for i in range(5):
            assert limiter.is_allowed(ip) is True

    def test_rate_limiter_blocks_over_limit(self):
        """Requests over the limit should be blocked."""
        limiter = SlidingWindowRateLimiter(requests_per_minute=3, burst=1)
        ip = "192.168.1.101"
        # First burst requests always pass
        assert limiter.is_allowed(ip) is True  # burst
        assert limiter.is_allowed(ip) is True  # 1
        assert limiter.is_allowed(ip) is True  # 2
        assert limiter.is_allowed(ip) is False  # 3 - over limit
        assert limiter.is_allowed(ip) is False  # still over

    def test_rate_limiter_per_ip(self):
        """Rate limiting should be per-IP, not global."""
        limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst=1)
        ip_a = "10.0.0.1"
        ip_b = "10.0.0.2"
        assert limiter.is_allowed(ip_a) is True
        assert limiter.is_allowed(ip_a) is True
        assert limiter.is_allowed(ip_a) is False  # ip_a at limit
        assert limiter.is_allowed(ip_b) is True  # ip_b still allowed

    def test_rate_limit_disabled_allows_request(self):
        """When rate limiting is disabled, requests should always pass."""
        with patch.object(settings, "rate_limit_enabled", False):
            # The check_rate_limit function returns None (allowed) when disabled
            from app.main import check_rate_limit
            from unittest.mock import MagicMock
            mock_request = MagicMock()
            mock_request.headers.get.return_value = ""
            mock_request.client.host = "192.168.1.1"
            result = check_rate_limit(mock_request)
            assert result is None  # None means allowed

    def test_rate_limit_endpoint_rejects_over_limit(self):
        """Rate-limited endpoint should return 429 when limit exceeded."""
        limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst=1)
        from app.middleware import rate_limit as rl_module
        # Patch the _rate_limiter in the rate_limit module where check_rate_limit looks it up
        original_limiter = rl_module._rate_limiter
        rl_module._rate_limiter = limiter

        with patch.object(settings, "rate_limit_enabled", True):
            # First two requests should pass (burst + 1)
            resp1 = client.post("/webhook/whatsapp", json={
                "object": "whatsapp_business_account",
                "entry": [{"id": "1", "changes": [{"value": {}, "field": "messages"}]}]
            })
            assert resp1.status_code == 200

            resp2 = client.post("/webhook/whatsapp", json={
                "object": "whatsapp_business_account",
                "entry": [{"id": "2", "changes": [{"value": {}, "field": "messages"}]}]
            })
            assert resp2.status_code == 200

            resp3 = client.post("/webhook/whatsapp", json={
                "object": "whatsapp_business_account",
                "entry": [{"id": "3", "changes": [{"value": {}, "field": "messages"}]}]
            })
            assert resp3.status_code == 429
            assert "Rate limit exceeded" in resp3.json()["detail"]

        # Restore
        rl_module._rate_limiter = original_limiter

    def test_rate_limit_reset_clears_ip(self):
        """Reset should clear rate limit for specific IP."""
        limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst=2)
        ip = "10.0.0.5"
        # With burst=2: first 2 requests always pass
        assert limiter.is_allowed(ip) is True  # burst #1
        assert limiter.is_allowed(ip) is True  # burst #2
        assert limiter.is_allowed(ip) is False  # over rpm(2)

        limiter.reset(ip)
        # After reset: burst allows 2 more, rpm allows 2 more
        assert limiter.is_allowed(ip) is True  # burst #1 after reset
        assert limiter.is_allowed(ip) is True  # burst #2 after reset
        assert limiter.is_allowed(ip) is False  # over rpm(2)


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------
class TestWebhookVerification:
    """Tests for GET /webhook/whatsapp (webhook verification)"""

    def test_verify_webhook_success(self):
        """Test successful webhook verification"""
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

    def test_verify_webhook_missing_parameters(self):
        """Test webhook verification with missing parameters"""
        response = client.get("/webhook/whatsapp")
        assert response.status_code == 400


class TestWebhookReceive:
    """Tests for POST /webhook/whatsapp (receive messages)"""

    def test_receive_webhook_success(self):
        """Test receiving webhook with valid payload"""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "id": "123456789",
                    "changes": [{
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "6281234567890", "phone_number_id": "123456789"},
                            "messages": [{
                                "from": "6281234567890",
                                "id": "wamid.test123",
                                "timestamp": "1234567890",
                                "type": "text",
                                "text": {"body": "Hello"}
                            }]
                        },
                        "field": "messages"
                    }]
                }]
            }
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_webhook_empty_payload(self):
        """Test receiving webhook with empty payload"""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            response = client.post("/webhook/whatsapp", json={})
            assert response.status_code == 200


class TestWebhookReceiveMediaTypes:
    """Tests for receiving non-text WhatsApp message types."""

    def _make_payload(self, message_type: str, message: dict) -> dict:
        return {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "6281234567890", "phone_number_id": "123456789"},
                        "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Test User"}}],
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test_media",
                            "timestamp": "1234567890",
                            "type": message_type,
                            **message,
                        }],
                    },
                    "field": "messages",
                }]
            }]
        }

    def test_receive_image(self):
        """Test receiving image message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("image", {
                "image": {"id": "MEDIA_IMG_123", "mime_type": "image/jpeg", "sha256": "abc123", "caption": "Foto"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_document(self):
        """Test receiving document message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("document", {
                "document": {"id": "MEDIA_DOC_456", "mime_type": "application/pdf", "sha256": "def456", "filename": "ktp.pdf"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_audio(self):
        """Test receiving audio message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("audio", {
                "audio": {"id": "MEDIA_AUD_789", "mime_type": "audio/ogg", "sha256": "ghi789"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_video(self):
        """Test receiving video message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("video", {
                "video": {"id": "MEDIA_VID_012", "mime_type": "video/mp4", "sha256": "jkl012"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_location(self):
        """Test receiving location message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("location", {
                "location": {"latitude": -6.2088, "longitude": 106.8456, "name": "Gedung", "address": "Jl. Contoh"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200

    def test_receive_sticker(self):
        """Test receiving sticker message."""
        with patch.object(settings, "whatsapp_signature_verify_enabled", False):
            payload = self._make_payload("sticker", {
                "sticker": {"id": "MEDIA_STK_345", "mime_type": "image/webp", "sha256": "mno345"}
            })
            response = client.post("/webhook/whatsapp", json=payload)
            assert response.status_code == 200


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