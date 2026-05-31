"""Tests for broker publisher service"""
import pytest
from unittest.mock import patch

from app.services.broker_publisher import BrokerPublisher


class TestBuildWhatsAppEvent:
    """Tests for event builder"""

    def test_build_event_basic(self):
        """Test building a basic WhatsApp event"""
        publisher = BrokerPublisher()
        event = publisher.build_whatsapp_event(
            contact_id="6281234567890",
            message_type="text",
            text_body="Hello",
            message_id="wamid.test123",
        )

        assert event["event_name"] == "whatsapp.message.received"
        assert event["contact_id"] == "6281234567890"
        assert event["message_type"] == "text"
        assert event["text_body"] == "Hello"
        assert event["source"] == "gateway"
        assert "timestamp" in event
        assert event["event_id"] == "wamid.test123"

    def test_build_event_without_message_id(self):
        """Test building event without message_id generates one"""
        publisher = BrokerPublisher()
        event = publisher.build_whatsapp_event(
            contact_id="6281234567890",
            message_type="text",
            text_body="Hello",
        )

        # No message_id provided, so event_id should be auto-generated
        assert event.get("message_id") is None
        assert event["event_id"] is not None
        assert event["event_id"].startswith("evt_")

    def test_build_event_with_raw_payload_summary(self):
        """Test building event with raw_payload_summary"""
        publisher = BrokerPublisher()
        event = publisher.build_whatsapp_event(
            contact_id="6281234567890",
            message_type="text",
            text_body="Hello",
            raw_payload_summary={
                "messaging_product": "whatsapp",
                "display_phone_number": "6281234567890",
            },
        )

        assert event["raw_payload_summary"]["messaging_product"] == "whatsapp"
        assert event["raw_payload_summary"]["display_phone_number"] == "6281234567890"


class TestPublishEvent:
    """Tests for publish_event"""

    def test_publish_skipped_when_disabled(self):
        """Test that publish is skipped when broker_enabled is False"""
        with patch.object(BrokerPublisher, "__init__", lambda self: None):
            publisher = BrokerPublisher()
            publisher.enabled = False
            publisher.api_url = "http://localhost"
            publisher.api_key = "test-key"

            event = {"event_name": "test"}
            result = publisher.publish_event(event)

            # Should return True (success) but NOT call broker
            assert result is True

    def test_publish_skipped_when_no_url(self):
        """Test publish skipped when broker URL not configured"""
        with patch.object(BrokerPublisher, "__init__", lambda self: None):
            publisher = BrokerPublisher()
            publisher.enabled = True
            publisher.api_url = ""
            publisher.api_key = "test-key"

            event = {"event_name": "test"}
            result = publisher.publish_event(event)

            assert result is True  # Graceful skip

    def test_publish_skipped_when_no_api_key(self):
        """Test publish skipped when API key not configured"""
        with patch.object(BrokerPublisher, "__init__", lambda self: None):
            publisher = BrokerPublisher()
            publisher.enabled = True
            publisher.api_url = "http://localhost"
            publisher.api_key = ""

            event = {"event_name": "test"}
            result = publisher.publish_event(event)

            assert result is True  # Graceful skip

    def test_publish_returns_true_when_broker_fails(self):
        """Test that publish returns True even when broker call fails"""
        with patch.object(BrokerPublisher, "__init__", lambda self: None):
            publisher = BrokerPublisher()
            publisher.enabled = True
            publisher.api_url = "http://localhost"
            publisher.api_key = "test-key"

            event = {"event_name": "whatsapp.message.received", "contact_id": "6281234567890"}

            # Mock httpx.Client to raise an exception
            with patch("httpx.Client") as mock_client:
                mock_client.return_value.post.side_effect = Exception("Connection refused")
                mock_client.return_value.__enter__ = lambda self: mock_client.return_value
                mock_client.return_value.__exit__ = lambda self, *args: None

                result = publisher.publish_event(event)

                # Should return True even on failure (gateway doesn't block)
                assert result is True