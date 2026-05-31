"""Pydantic schemas for WhatsApp API"""
from pydantic import BaseModel, Field
from typing import Optional


class SendMessageRequest(BaseModel):
    """Request schema for sending WhatsApp message"""
    to: str = Field(..., description="Recipient phone number (E.164 format, e.g., 6281234567890)")
    message: str = Field(..., description="Message text to send", min_length=1)
    
    class Config:
        json_schema_extra = {
            "example": {
                "to": "6281234567890",
                "message": "Hello from KTA WhatsApp Gateway!"
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
