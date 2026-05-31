"""Health check endpoint"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint
    
    Returns:
        dict: Status message
    """
    return {
        "status": "ok",
        "service": "KTA WhatsApp Gateway",
        "version": "0.1.0"
    }
