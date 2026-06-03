"""Pydantic schemas for WhatsApp API"""
from pydantic import BaseModel, Field
from typing import Optional


class SendMessageRequest(BaseModel):
    """Request schema for sending WhatsApp message"""
    to: str = Field(..., description="Recipient phone number (E.164 format, e.g., 6281234567890)")
    message: str = Field(..., description="Message text to send", min_length=1)
    reply_to: Optional[str] = Field(None, description="Original message ID this reply refers to (for Phase 2 dedup/trace)")
    metadata: Optional[dict] = Field(None, description="Optional metadata: source_service, trace_id, etc. (for Phase 2 dedup/trace)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "to": "6281234567890",
                "message": "Hello from KTA WhatsApp Gateway!",
                "reply_to": "wamid.HBgLNjI4MTIz...",
                "metadata": {"source_service": "wa-router", "trace_id": "gw-20260531143000"}
            }
        }


class SendMessageResponse(BaseModel):
    """Response schema for send message endpoint"""
    status: str
    message_id: Optional[str] = None
    error: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message_id": "wamid.HBgLNjI4MTIzNDU2Nzg5MBUCABIYFjNFQjBDMUQxRjg5QzRGNEE4RjAw"
            }
        }
