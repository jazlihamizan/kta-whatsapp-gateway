"""Prometheus metrics endpoint"""
from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from app.metrics import get_metrics, get_content_type

router = APIRouter()


@router.get("/metrics")
def metrics():
    """Expose Prometheus metrics for scraping."""
    return Response(
        content=get_metrics(),
        media_type=get_content_type(),
    )