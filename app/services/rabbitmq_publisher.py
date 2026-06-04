"""RabbitMQ publisher service for WhatsApp events.

Publishes structured WhatsApp events to RabbitMQ exchange `wa.events`.
Does NOT publish to broker REST API.
"""
import logging
import json
from datetime import datetime, timezone
from typing import Optional
import aio_pika
from aio_pika import ExchangeType

from app.config import settings

logger = logging.getLogger(__name__)


def build_routing_key(message_type: str) -> str:
    """Map message type to routing key."""
    type_map = {
        "text": "wa.inbound.text",
        "image": "wa.inbound.image",
        "document": "wa.inbound.document",
        "video": "wa.inbound.video",
        "audio": "wa.inbound.audio",
        "sticker": "wa.inbound.sticker",
        "location": "wa.inbound.location",
        "contacts": "wa.inbound.contacts",
        "reaction": "wa.inbound.reaction",
    }
    return type_map.get(message_type, "wa.inbound.unknown")


def build_wa_event(
    event_id: Optional[str],
    phone_number_id: str,
    sender_phone: str,
    sender_wa_id: Optional[str],
    sender_name: Optional[str],
    message_id: str,
    message_type: str,
    text_body: Optional[str],
    message_timestamp: int,
    raw_payload_summary: Optional[dict],
    media_info: Optional[dict] = None,
) -> dict:
    """
    Build a structured WhatsApp event for RabbitMQ.

    Args:
        event_id: Optional event ID override
        phone_number_id: WhatsApp phone number ID from metadata
        sender_phone: Sender's phone number
        sender_wa_id: Sender's WA ID
        sender_name: Sender's display name
        message_id: Unique message ID from Meta
        message_type: Type of message (text, image, etc.)
        text_body: Text body if message_type is text
        message_timestamp: Unix timestamp of message
        raw_payload_summary: Non-sensitive payload metadata
        media_info: Optional media metadata (id, mime_type, caption, etc.)

    Returns:
        Structured event dict
    """
    message_data: dict = {
        "id": message_id,
        "type": message_type,
        "text_body": text_body or "",
        "timestamp": message_timestamp,
    }
    if media_info:
        message_data["media"] = media_info

    return {
        "event_name": "whatsapp.message.received",
        "event_id": event_id or f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "gateway",
        "phone_number_id": phone_number_id,
        "sender": {
            "phone": sender_phone,
            "wa_id": sender_wa_id or "",
            "name": sender_name or "",
        },
        "message": message_data,
        "context": {
            "trace_id": f"gw-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        },
        "metadata": {
            "messaging_product": raw_payload_summary.get("messaging_product", "whatsapp") if raw_payload_summary else "whatsapp",
        },
    }


class RabbitMQPublisher:
    """Async RabbitMQ publisher for WhatsApp events."""

    def __init__(self):
        self.enabled = settings.wa_events_enabled
        self.url = settings.rabbitmq_url
        self.exchange_name = settings.wa_events_exchange
        self._connection: Optional[aio_pika.Connection] = None
        self._channel: Optional[aio_pika.Channel] = None
        self._exchange: Optional[aio_pika.Exchange] = None

    async def _ensure_connection(self):
        """Ensure RabbitMQ connection is established."""
        if self._connection and not self._connection.is_closed:
            return

        try:
            self._connection = await aio_pika.connect_robust(self.url, timeout=10.0)
            self._channel = await self._connection.channel()
            self._exchange = await self._channel.declare_exchange(
                self.exchange_name,
                ExchangeType.TOPIC,
                durable=True,
            )
            logger.info(f"Connected to RabbitMQ, exchange '{self.exchange_name}' declared")
        except Exception as e:
            logger.error(f"RabbitMQ connection failed: {e}")
            self._connection = None
            self._channel = None
            self._exchange = None
            raise

    async def publish(self, event: dict, routing_key: str) -> bool:
        """
        Publish event to RabbitMQ.

        Args:
            event: Structured event dict
            routing_key: RabbitMQ routing key

        Returns:
            True if published successfully, False on error
        """
        if not self.enabled:
            logger.debug("WA_EVENTS_ENABLED=false, skipping RabbitMQ publish")
            return True

        try:
            await self._ensure_connection()
            if not self._exchange:
                return False

            message = aio_pika.Message(
                body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await self._exchange.publish(message, routing_key=routing_key)
            logger.info(f"Published event {event.get('event_id')} to {routing_key}")
            return True

        except Exception as e:
            logger.error(f"Failed to publish event to RabbitMQ: {e}")
            return False  # Return False so caller can update event_store status to 'failed'

    async def close(self):
        """Close RabbitMQ connection."""
        if self._connection and not self._connection.is_closed:
            await self._connection.close()


# Global instance
rabbitmq_publisher = RabbitMQPublisher()