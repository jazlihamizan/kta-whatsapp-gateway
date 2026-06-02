"""Tests for RabbitMQ WhatsApp events publisher"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.rabbitmq_publisher import (
    build_wa_event,
    build_routing_key,
    RabbitMQPublisher,
)


class TestBuildRoutingKey:
    """Tests for routing key mapping"""

    def test_routing_key_text(self):
        assert build_routing_key("text") == "wa.inbound.text"

    def test_routing_key_image(self):
        assert build_routing_key("image") == "wa.inbound.image"

    def test_routing_key_document(self):
        assert build_routing_key("document") == "wa.inbound.document"

    def test_routing_key_video(self):
        assert build_routing_key("video") == "wa.inbound.video"

    def test_routing_key_audio(self):
        assert build_routing_key("audio") == "wa.inbound.audio"

    def test_routing_key_sticker(self):
        assert build_routing_key("sticker") == "wa.inbound.sticker"

    def test_routing_key_unknown(self):
        assert build_routing_key("unknown_type") == "wa.inbound.unknown"
        assert build_routing_key("") == "wa.inbound.unknown"


class TestBuildWAEvent:
    """Tests for structured WA event builder"""

    def test_build_event_basic_text(self):
        """Test building a basic text message event"""
        event = build_wa_event(
            event_id="wamid.test123",
            phone_number_id="1091317450740252",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name="John Doe",
            message_id="wamid.test123",
            message_type="text",
            text_body="Hello World",
            message_timestamp=1234567890,
            raw_payload_summary={"messaging_product": "whatsapp"},
        )

        assert event["event_name"] == "whatsapp.message.received"
        assert event["event_id"] == "wamid.test123"
        assert event["source"] == "gateway"
        assert event["phone_number_id"] == "1091317450740252"
        assert event["sender"]["phone"] == "6281234567890"
        assert event["sender"]["wa_id"] == "6281234567890"
        assert event["sender"]["name"] == "John Doe"
        assert event["message"]["id"] == "wamid.test123"
        assert event["message"]["type"] == "text"
        assert event["message"]["text_body"] == "Hello World"
        assert event["message"]["timestamp"] == 1234567890
        assert event["context"]["trace_id"]
        assert event["metadata"]["messaging_product"] == "whatsapp"

    def test_build_event_autogenerates_event_id(self):
        """Test that event_id is auto-generated if not provided"""
        event = build_wa_event(
            event_id=None,
            phone_number_id="1091317450740252",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name=None,
            message_id="wamid.test456",
            message_type="image",
            text_body=None,
            message_timestamp=1234567890,
            raw_payload_summary={},
        )

        assert event["event_id"].startswith("evt_")

    def test_build_event_no_sensitive_data(self):
        """Test that event does NOT contain tokens, secrets, or raw credentials"""
        event = build_wa_event(
            event_id="wamid.test789",
            phone_number_id="1091317450740252",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name="Test User",
            message_id="wamid.test789",
            message_type="text",
            text_body="Test message",
            message_timestamp=1234567890,
            raw_payload_summary={},
        )

        # Verify no tokens or secrets in event
        event_str = str(event).lower()
        assert "token" not in event_str
        assert "secret" not in event_str
        assert "password" not in event_str
        assert "eaag" not in event_str  # Meta token pattern
        assert "eaa" not in event_str  # Common token prefix
        assert "bearer" not in event_str


class TestRabbitMQPublisher:
    """Tests for RabbitMQ publisher behavior"""

    @pytest.mark.asyncio
    async def test_publisher_disabled_returns_true(self):
        """Test that when WA_EVENTS_ENABLED=false, publish returns True (webhook still 200)"""
        publisher = RabbitMQPublisher()
        publisher.enabled = False

        result = await publisher.publish({}, "wa.inbound.text")
        assert result is True  # Should not block webhook

    @pytest.mark.asyncio
    async def test_publish_returns_true_on_error(self):
        """Test that connection/publish error returns True (webhook still 200)"""
        publisher = RabbitMQPublisher()
        publisher.enabled = True

        # _ensure_connection raises exception
        with patch.object(publisher, '_ensure_connection', side_effect=Exception("Connection failed")):
            result = await publisher.publish({"event": "test"}, "wa.inbound.text")
            assert result is True  # Should still return True so webhook returns 200

    @pytest.mark.asyncio
    async def test_publish_success_returns_true(self):
        """Test successful publish returns True"""
        publisher = RabbitMQPublisher()
        publisher.enabled = True

        mock_exchange = AsyncMock()
        mock_channel = AsyncMock()
        mock_connection = MagicMock()
        mock_connection.is_closed = False

        publisher._connection = mock_connection
        publisher._channel = mock_channel
        publisher._exchange = mock_exchange

        event = build_wa_event(
            event_id="wamid.test",
            phone_number_id="123",
            sender_phone="6280000000000",
            sender_wa_id="6280000000000",
            sender_name="Test",
            message_id="wamid.test",
            message_type="text",
            text_body="Hello",
            message_timestamp=1234567890,
            raw_payload_summary={},
        )

        result = await publisher.publish(event, "wa.inbound.text")
        assert result is True


class TestNoBrokerAPICall:
    """Tests that WhatsApp events are NOT sent to /v1/agent (old broker pattern)"""

    def test_event_structure_has_no_broker_api_fields(self):
        """Verify event structure does not include /v1/agent or broker_api_url fields"""
        event = build_wa_event(
            event_id="wamid.test999",
            phone_number_id="1091317450740252",
            sender_phone="6280000000000",
            sender_wa_id="6280000000000",
            sender_name="Test User",
            message_id="wamid.test999",
            message_type="text",
            text_body="Test",
            message_timestamp=1234567890,
            raw_payload_summary={},
        )

        # Event should not contain broker API references
        event_str = str(event)
        assert "/v1/agent" not in event_str
        assert "broker_api_url" not in event_str
        assert "prompt" not in event_str.lower()  # Old pattern used prompt=