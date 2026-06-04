"""Tests for gateway WhatsApp event format and contract.

These tests validate that:
1. build_wa_event() produces events with the correct structure
2. build_routing_key() produces correct routing keys for all message types
3. The event structure matches what the broker WA router consumer expects
"""
import pytest
from datetime import datetime, timezone

from app.services.rabbitmq_publisher import build_wa_event, build_routing_key


class TestBuildWAEvent:
    """Tests for build_wa_event() output structure."""

    def test_event_has_required_fields(self):
        """Event must have all required fields for broker consumer."""
        event = build_wa_event(
            event_id="evt_test001",
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name="Test User",
            message_id="wamid.test123",
            message_type="text",
            text_body="Halo dunia",
            message_timestamp=1234567890,
            raw_payload_summary={"messaging_product": "whatsapp"},
        )

        # Top-level required fields
        assert "event_name" in event
        assert "event_id" in event
        assert "timestamp" in event
        assert "source" in event
        assert event["source"] == "gateway"

        # sender block
        assert "sender" in event
        assert "phone" in event["sender"]
        assert "wa_id" in event["sender"]
        assert "name" in event["sender"]

        # message block
        assert "message" in event
        assert "id" in event["message"]
        assert "type" in event["message"]
        assert "text_body" in event["message"]
        assert "timestamp" in event["message"]

        # context.trace_id (for tracing across services)
        assert "context" in event
        assert "trace_id" in event["context"]

    def test_event_id_auto_generated_when_none(self):
        """If event_id is None, auto-generate one."""
        event = build_wa_event(
            event_id=None,
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id=None,
            sender_name=None,
            message_id="wamid.test456",
            message_type="text",
            text_body="Test",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        assert event["event_id"] is not None
        assert event["event_id"].startswith("evt_")

    def test_event_empty_text_body_ok(self):
        """text_body can be None/empty for non-text messages."""
        event = build_wa_event(
            event_id="evt_test002",
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name=None,
            message_id="wamid.img001",
            message_type="image",
            text_body=None,
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        assert event["message"]["text_body"] == ""
        assert event["message"]["type"] == "image"

    def test_event_media_info_attached(self):
        """media_info is attached when provided (image, audio, etc.)."""
        event = build_wa_event(
            event_id="evt_test003",
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id="6281234567890",
            sender_name=None,
            message_id="wamid.img002",
            message_type="image",
            text_body=None,
            message_timestamp=1234567890,
            raw_payload_summary=None,
            media_info={
                "id": "MEDIA_IMG_123",
                "mime_type": "image/jpeg",
                "sha256": "abc123",
                "caption": "Foto KTP",
            },
        )
        assert "media" in event["message"]
        assert event["message"]["media"]["id"] == "MEDIA_IMG_123"
        assert event["message"]["media"]["caption"] == "Foto KTP"
        # Sensitive fields should not be leaked
        assert "access_token" not in str(event)

    def test_event_no_v1_agent_reference(self):
        """Event should NOT contain /v1/agent or prompt fields."""
        event = build_wa_event(
            event_id="evt_test004",
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id=None,
            sender_name=None,
            message_id="wamid.test005",
            message_type="text",
            text_body="Test message",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        event_str = str(event).lower()
        assert "/v1/agent" not in event_str
        assert "prompt" not in event_str

    def test_event_sender_wa_id_optional(self):
        """sender.wa_id can be None (for incoming events without WA ID lookup)."""
        event = build_wa_event(
            event_id="evt_test005",
            phone_number_id="123456789",
            sender_phone="6281234567890",
            sender_wa_id=None,
            sender_name="Some Name",
            message_id="wamid.test006",
            message_type="text",
            text_body="Hello",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        assert event["sender"]["wa_id"] == ""
        assert event["sender"]["name"] == "Some Name"

    def test_event_timestamp_iso_format(self):
        """timestamp field must be ISO 8601 format."""
        event = build_wa_event(
            event_id="evt_test006",
            phone_number_id="123456789",
            sender_phone="6280000000000",
            sender_wa_id=None,
            sender_name=None,
            message_id="wamid.test007",
            message_type="text",
            text_body="Test",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        # Should be parseable as ISO 8601 (with or without Z suffix)
        ts = event["timestamp"]
        assert "T" in ts  # ISO format contains T separator
        assert "+" in ts or "Z" in ts  # timezone info present
        from datetime import datetime
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.year >= 2024  # reasonable year check


class TestBuildRoutingKey:
    """Tests for build_routing_key() output."""

    def test_routing_key_text(self):
        assert build_routing_key("text") == "wa.inbound.text"

    def test_routing_key_image(self):
        assert build_routing_key("image") == "wa.inbound.image"

    def test_routing_key_audio(self):
        assert build_routing_key("audio") == "wa.inbound.audio"

    def test_routing_key_video(self):
        assert build_routing_key("video") == "wa.inbound.video"

    def test_routing_key_document(self):
        assert build_routing_key("document") == "wa.inbound.document"

    def test_routing_key_sticker(self):
        assert build_routing_key("sticker") == "wa.inbound.sticker"

    def test_routing_key_location(self):
        assert build_routing_key("location") == "wa.inbound.location"

    def test_routing_key_contacts(self):
        assert build_routing_key("contacts") == "wa.inbound.contacts"

    def test_routing_key_reaction(self):
        assert build_routing_key("reaction") == "wa.inbound.reaction"

    def test_routing_key_interactive_type(self):
        """Interactive message types should route to wa.inbound.interactive."""
        assert build_routing_key("interactive") == "wa.inbound.interactive"

    def test_routing_key_unknown_type(self):
        """Unknown message types should fallback to wa.inbound.unknown."""
        assert build_routing_key("completely_fake_type") == "wa.inbound.unknown"


class TestEventContractWithBroker:
    """
    Contract tests: verify gateway event format is consumable by broker WA router.

    These tests import broker code directly — they require kta-async-broker repo
    to be present and are SKIPPED by default unless RUN_CROSS_REPO_CONTRACT=1.

    This ensures gateway CI stays self-contained and doesn't fail if broker repo
    is not available (e.g., shallow clone, different CI runner).
    """

    def test_event_structure_consumable_by_broker_classifier(self):
        """
        Build a gateway event, then verify broker's classify_intent() can parse it.

        SKIPPED by default — requires kta-async-broker repo at ~/kta-async-broker.
        Set RUN_CROSS_REPO_CONTRACT=1 to enable.
        """
        import os
        if os.getenv("RUN_CROSS_REPO_CONTRACT", "0") not in ("1", "true", "yes"):
            pytest.skip("Requires RUN_CROSS_REPO_CONTRACT=1 and kta-async-broker repo at ~/kta-async-broker")

        import sys
        broker_path = os.path.expanduser("~/kta-async-broker")
        if broker_path not in sys.path:
            sys.path.insert(0, broker_path)

        from services.wa_router.consumer import classify_intent

        event = build_wa_event(
            event_id="evt_contract001",
            phone_number_id="123456789",
            sender_phone="6280000000000",
            sender_wa_id="6280000000000",
            sender_name="Contract Test",
            message_id="wamid.contract001",
            message_type="text",
            text_body="Halo, apa kabar?",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )

        text_body = event.get("message", {}).get("text_body", "")
        sender_phone = event.get("sender", {}).get("phone", "")
        message_id = event.get("message", {}).get("id", "")

        assert sender_phone == "6280000000000"
        assert message_id == "wamid.contract001"
        assert text_body == "Halo, apa kabar?"
        assert classify_intent(text_body) == "greeting"

    def test_event_structure_with_media_consumable_by_broker(self):
        """Media events (no text_body) should be processed without errors by broker."""
        import os
        if os.getenv("RUN_CROSS_REPO_CONTRACT", "0") not in ("1", "true", "yes"):
            pytest.skip("Requires RUN_CROSS_REPO_CONTRACT=1 and kta-async-broker repo at ~/kta-async-broker")

        import sys
        broker_path = os.path.expanduser("~/kta-async-broker")
        if broker_path not in sys.path:
            sys.path.insert(0, broker_path)

        from services.wa_router.consumer import classify_intent

        event = build_wa_event(
            event_id="evt_contract002",
            phone_number_id="123456789",
            sender_phone="6280000000000",
            sender_wa_id="6280000000000",
            sender_name="Media Test",
            message_id="wamid.media001",
            message_type="image",
            text_body=None,
            message_timestamp=1234567890,
            raw_payload_summary=None,
            media_info={"id": "MEDIA_IMG_TEST", "mime_type": "image/jpeg", "caption": "Foto KTP"},
        )

        text_body = event.get("message", {}).get("text_body", "")
        assert text_body == ""
        assert classify_intent(text_body) == "unknown"
        assert event.get("message", {}).get("media", {}).get("caption") == "Foto KTP"

    def test_reply_payload_schema_matches_gateway_send_message(self):
        """
        Verify broker's build_reply_payload() produces a payload matching gateway schema.

        SKIPPED by default — requires kta-async-broker repo at ~/kta-async-broker.
        Set RUN_CROSS_REPO_CONTRACT=1 to enable.
        """
        import os
        if os.getenv("RUN_CROSS_REPO_CONTRACT", "0") not in ("1", "true", "yes"):
            pytest.skip("Requires RUN_CROSS_REPO_CONTRACT=1 and kta-async-broker repo at ~/kta-async-broker")

        import sys
        broker_path = os.path.expanduser("~/kta-async-broker")
        if broker_path not in sys.path:
            sys.path.insert(0, broker_path)

        from services.wa_router.consumer import build_reply_payload

        payload = build_reply_payload(
            sender="6280000000000",
            reply_text="Terima kasih!",
            reply_to="wamid.original001",
            metadata={"event_id": "evt_test001", "intent": "menu_help"},
        )

        assert "to" in payload
        assert "message" in payload
        assert "reply_to" in payload  # top-level field
        assert "metadata" in payload
        assert "context" not in payload
        assert payload["metadata"]["event_id"] == "evt_test001"
        payload_str = str(payload).lower()
        assert "/v1/agent" not in payload_str
        assert "prompt" not in payload_str

    def test_no_prompt_or_v1_agent_in_event(self):
        """Event must not contain /v1/agent or prompt fields (broker routing rule)."""
        event = build_wa_event(
            event_id="evt_contract003",
            phone_number_id="123456789",
            sender_phone="6280000000000",
            sender_wa_id=None,
            sender_name=None,
            message_id="wamid.test003",
            message_type="text",
            text_body="Test routing",
            message_timestamp=1234567890,
            raw_payload_summary=None,
        )
        event_str = str(event)
        assert "/v1/agent" not in event_str
        assert "'prompt'" not in event_str