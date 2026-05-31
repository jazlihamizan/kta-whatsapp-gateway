"""Broker publisher service for sending WhatsApp events to the async broker."""
import logging
from datetime import datetime, timezone
from typing import Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class BrokerPublisher:
    """Publish WhatsApp events to the async broker API."""

    def __init__(self):
        self.enabled = settings.broker_enabled
        self.api_url = settings.broker_api_url.rstrip("/") if settings.broker_api_url else ""
        self.api_key = settings.broker_api_key

    def build_whatsapp_event(
        self,
        contact_id: str,
        message_type: str,
        text_body: Optional[str] = None,
        message_id: Optional[str] = None,
        raw_payload_summary: Optional[dict] = None,
    ) -> dict:
        """
        Build a WhatsApp message received event payload.

        Args:
            contact_id: Sender's phone number (E.164 format)
            message_type: Type of message (text, image, document, etc.)
            text_body: Plain text body if message_type is text
            message_id: Unique message ID from Meta
            raw_payload_summary: Summary of the raw Meta payload (no secrets)

        Returns:
            Event dict ready to be published
        """
        return {
            "event_name": "whatsapp.message.received",
            "event_id": message_id or f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "gateway",
            "contact_id": contact_id,
            "message_type": message_type,
            "text_body": text_body,
            "raw_payload_summary": raw_payload_summary or {},
        }

    def publish_event(self, event: dict) -> bool:
        """
        Publish an event to the broker API (non-blocking, sync).

        Args:
            event: Event dict to publish

        Returns:
            Always True — gateway never blocks Meta webhook even if broker fails.
        """
        if not self.enabled:
            logger.debug("Broker disabled, skipping publish")
            return True

        if not self.api_url or not self.api_key:
            logger.warning("Broker enabled but BROKER_API_URL or BROKER_API_KEY not set")
            return True

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.api_url}/v1/agent",
                    json={"prompt": str(event), "priority": "normal", "metadata": {"source": "whatsapp_gateway"}},
                    headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                )
                response.raise_for_status()
                logger.info(f"Event published to broker: {event.get('event_id')}")
                return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Broker HTTP error: {e.response.status_code} - {e.response.text}")
            return True  # Still return True to not block Meta webhook

        except Exception as e:
            logger.error(f"Broker publish failed: {str(e)}")
            return True  # Still return True to not block Meta webhook


# Global instance
broker_publisher = BrokerPublisher()