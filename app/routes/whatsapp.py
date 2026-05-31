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
from app.services.broker_publisher import broker_publisher
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
    """
    Webhook verification endpoint for Meta WhatsApp Cloud API
    
    Meta will call this endpoint with hub.mode, hub.verify_token, and hub.challenge
    to verify the webhook URL.
    
    Args:
        hub_mode: Should be "subscribe"
        hub_verify_token: Token to verify (must match WHATSAPP_VERIFY_TOKEN)
        hub_challenge: Challenge string to return if verification succeeds
    
    Returns:
        str: hub.challenge if verification succeeds
    
    Raises:
        HTTPException: 403 if verification fails
    """
    logger.info(f"Webhook verification request: mode={hub_mode}, token={hub_verify_token[:10] if hub_verify_token else None}...")
    
    # Check if all required parameters are present
    if not hub_mode or not hub_verify_token or not hub_challenge:
        logger.error("Missing required parameters for webhook verification")
        raise HTTPException(status_code=400, detail="Missing required parameters")
    
    # Check if mode is subscribe
    if hub_mode != "subscribe":
        logger.error(f"Invalid hub.mode: {hub_mode}")
        raise HTTPException(status_code=400, detail="Invalid hub.mode")
    
    # Verify token
    if hub_verify_token != settings.whatsapp_verify_token:
        logger.error("Invalid verify token")
        raise HTTPException(status_code=403, detail="Invalid verify token")
    
    logger.info("Webhook verification successful")
    return PlainTextResponse(content=hub_challenge, media_type="text/plain")


@router.post("/webhook/whatsapp")
async def receive_webhook(request: Request):
    """
    Receive incoming WhatsApp messages from Meta
    
    This endpoint receives webhook events from Meta WhatsApp Cloud API
    when users send messages to the WhatsApp Business number.
    
    Args:
        request: FastAPI Request object containing the webhook payload
    
    Returns:
        dict: Success response
    """
    try:
        body = await request.json()
        logger.info(f"Received webhook: {body}")
        
        # Extract message data if present
        if "entry" in body:
            for entry in body["entry"]:
                if "changes" in entry:
                    for change in entry["changes"]:
                        if "value" in change:
                            value = change["value"]
                            
                            # Check if there are messages
                            if "messages" in value:
                                for message in value["messages"]:
                                    from_number = message.get("from")
                                    message_type = message.get("type")
                                    message_id = message.get("id")
                                    text_body = None
                                    if message_type == "text":
                                        text_body = message.get("text", {}).get("body")
                                    # Log to JSONL file for persistence
                                    _log_webhook_event(
                                        event_type="webhook_received",
                                        sender=from_number,
                                        message_type=message_type,
                                        text_body=text_body,
                                        raw_payload=body
                                    )
                                    logger.info(f"Message received - From: {from_number}, Type: {message_type}, ID: {message_id}")
                                    
                                    # Build and publish event to broker (non-blocking)
                                    event = broker_publisher.build_whatsapp_event(
                                        contact_id=from_number,
                                        message_type=message_type,
                                        text_body=text_body,
                                        message_id=message_id,
                                        raw_payload_summary={
                                            "messaging_product": value.get("messaging_product"),
                                            "display_phone_number": value.get("metadata", {}).get("display_phone_number"),
                                            "contact_id": value.get("contacts", [{}])[0].get("wa_id") if value.get("contacts") else None,
                                        },
                                    )
                                    broker_publisher.publish_event(event)
        
        return {"status": "ok"}
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


@router.post("/send-message", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest):
    """
    Send a WhatsApp message
    
    This endpoint allows sending text messages via WhatsApp Cloud API.
    
    Args:
        request: SendMessageRequest containing recipient number and message text
    
    Returns:
        SendMessageResponse: Status and message ID if successful
    
    Raises:
        HTTPException: 500 if sending fails
    """
    try:
        result = await whatsapp_service.send_message(request.to, request.message)
        
        # Extract message ID from Meta response
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
