"""WhatsApp webhook endpoints"""
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from typing import Optional
import logging
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.services.whatsapp_service import WhatsAppService
from app.services.rabbitmq_publisher import rabbitmq_publisher, build_wa_event, build_routing_key
from app.schemas.whatsapp import SendMessageRequest, SendMessageResponse

LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "webhook_events.jsonl"

router = APIRouter()
logger = logging.getLogger(__name__)
whatsapp_service = WhatsAppService()


def _log_webhook_event(event_type: str, sender: str = None, message_type: str = None, text_body: str = None, raw_payload: dict = None):
    """Write a webhook event to the JSONL log file (no tokens logged)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        event = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "source": "webhook_whatsapp",
            "event_type": event_type
        }
        if sender:
            event["sender"] = sender
        if message_type:
            event["message_type"] = message_type
        if text_body:
            event["text_body"] = text_body
        # Only include safe, non-sensitive payload fields (no tokens, no access_token)
        if raw_payload:
            safe_payload = {k: v for k, v in raw_payload.items() if k not in ("access_token", "token", "verify_token", "password")}
            event["raw_payload_summary"] = {k: str(v)[:100] for k, v in safe_payload.items()}
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Failed to write webhook log: {e}")


@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge")
):
    """Webhook verification for Meta WhatsApp Cloud API."""
    if not hub_mode or not hub_verify_token or not hub_challenge:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="Invalid hub.mode")

    if hub_verify_token != settings.whatsapp_verify_token:
        raise HTTPException(status_code=403, detail="Invalid verify token")

    logger.info("Webhook verification successful")
    return PlainTextResponse(content=hub_challenge, media_type="text/plain")


def _extract_media_info(message: dict) -> dict:
    """Extract media metadata from a non-text WhatsApp message.

    Returns a dict with media_id, mime_type, sha256, filename (if available),
    and caption (if available).  Returns empty dict for unknown types.
    """
    msg_type = message.get("type", "")
    type_block = message.get(msg_type, {})

    if not isinstance(type_block, dict):
        return {}

    info: dict = {}

    # Common media fields (image, document, audio, video, sticker)
    for field in ("id", "mime_type", "sha256", "filename", "caption"):
        if field in type_block:
            info[field] = type_block[field]

    # Location type has different structure
    if msg_type == "location":
        info["id"] = message.get("id", "")
        for loc_field in ("latitude", "longitude", "name", "address"):
            if loc_field in type_block:
                info[loc_field] = type_block[loc_field]

    return info


@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request):
    """
    Receive incoming WhatsApp messages from Meta.
    Validates, parses, publishes to RabbitMQ, returns 200 to Meta.
    Does NOT perform business logic.
    """
    try:
        body = await request.json()
        logger.info(f"Received webhook payload")

        if "entry" in body:
            for entry in body["entry"]:
                if "changes" in entry:
                    for change in entry["changes"]:
                        if "value" in change:
                            value = change["value"]
                            metadata = value.get("metadata", {})
                            phone_number_id = metadata.get("phone_number_id", "")
                            messaging_product = value.get("messaging_product", "whatsapp")

                            if "messages" in value:
                                for message in value["messages"]:
                                    from_number = message.get("from", "")
                                    message_type = message.get("type", "unknown")
                                    message_id = message.get("id", "")

                                    # --- Extract content by type ---
                                    text_body = None
                                    media_info = {}

                                    if message_type == "text":
                                        text_body = message.get("text", {}).get("body")
                                    elif message_type in ("image", "document", "audio", "video", "sticker", "location"):
                                        media_info = _extract_media_info(message)
                                    # other types (contacts, reaction, interactive, etc.)
                                    # remain as empty media_info — still published safely

                                    # Get sender info
                                    contacts = value.get("contacts", [])
                                    sender_name = None
                                    sender_wa_id = None
                                    for contact in contacts:
                                        if contact.get("wa_id") == from_number:
                                            sender_name = contact.get("profile", {}).get("name")
                                            sender_wa_id = contact.get("wa_id")
                                            break

                                    # Log to JSONL
                                    _log_webhook_event(
                                        event_type="webhook_received",
                                        sender=from_number,
                                        message_type=message_type,
                                        text_body=text_body,
                                        raw_payload=body
                                    )
                                    logger.info(f"Message - From: {from_number}, Type: {message_type}, ID: {message_id}")

                                    # Build structured event
                                    event = build_wa_event(
                                        event_id=None,
                                        phone_number_id=phone_number_id,
                                        sender_phone=from_number,
                                        sender_wa_id=sender_wa_id,
                                        sender_name=sender_name,
                                        message_id=message_id,
                                        message_type=message_type,
                                        text_body=text_body,
                                        message_timestamp=message.get("timestamp", ""),
                                        raw_payload_summary={
                                            "messaging_product": messaging_product,
                                        },
                                        media_info=media_info if media_info else None,
                                    )

                                    # Publish to RabbitMQ (async, non-blocking)
                                    routing_key = build_routing_key(message_type)
                                    await rabbitmq_publisher.publish(event, routing_key)

        # Always return 200 to Meta, even if RabbitMQ fails
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        # Still return 200 to Meta to prevent webhook retry storms
        return {"status": "ok"}


@router.post("/send-message", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """Send a WhatsApp message via Meta Graph API."""
    try:
        result = await whatsapp_service.send_message(request.to, request.message, reply_to=request.reply_to)

        message_id = None
        if "messages" in result and len(result["messages"]) > 0:
            message_id = result["messages"][0].get("id")

        return SendMessageResponse(
            status="success",
            message_id=message_id
        )

    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return SendMessageResponse(
            status="error",
            error=str(e)
        )