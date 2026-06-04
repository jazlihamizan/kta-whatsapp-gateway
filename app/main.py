"""KTA WhatsApp Gateway - Main FastAPI Application"""
import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import health, whatsapp, metrics
from app.middleware.rate_limit import check_rate_limit, _rate_limiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager — replaces @app.on_event startup/shutdown."""
    # Startup
    logger.info("Starting KTA WhatsApp Gateway...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Meta Graph API version: {settings.meta_graph_api_version}")

    # Signature verification (R1)
    if settings.whatsapp_signature_verify_enabled:
        logger.info("X-Hub-Signature-256 verification ENABLED")
        if not settings.whatsapp_app_secret:
            logger.warning("WHATSAPP_APP_SECRET is empty - signature verification will reject all requests!")
    else:
        logger.info("X-Hub-Signature-256 verification DISABLED (default dev mode)")

    # CORS (R3)
    logger.info(f"CORS allow_origins: {settings.cors_allow_origins}")

    # Rate limiting (R6)
    if settings.rate_limit_enabled:
        logger.info(f"Rate limiting ENABLED: {settings.rate_limit_requests_per_minute} req/min, burst {settings.rate_limit_burst}")
    else:
        logger.info("Rate limiting DISABLED (default)")

    # Event store (G1)
    if settings.event_store_enabled:
        from app.services.event_store import init_event_store
        init_event_store()
        logger.info(f"Event store ENABLED: {settings.event_store_db_path}")
    else:
        logger.info("Event store DISABLED (default dev mode)")

    # Verify critical settings
    if not settings.whatsapp_verify_token:
        logger.warning("WHATSAPP_VERIFY_TOKEN not set - webhook verification will fail")

    if not settings.whatsapp_access_token:
        logger.warning("WHATSAPP_ACCESS_TOKEN not set - sending messages will fail")

    if not settings.whatsapp_phone_number_id:
        logger.warning("WHATSAPP_PHONE_NUMBER_ID not set - sending messages will fail")

    yield  # application runs here

    # Shutdown
    logger.info("Shutting down KTA WhatsApp Gateway...")
    await whatsapp.whatsapp_service.close()
    from app.services.rabbitmq_publisher import rabbitmq_publisher
    await rabbitmq_publisher.close()


# Create FastAPI app with lifespan
app = FastAPI(
    title="KTA WhatsApp Gateway",
    description="API Gateway for WhatsApp Cloud API integration with KTA Partai UMMAT system",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS (R3) - Configurable via settings
# ---------------------------------------------------------------------------
cors_origins: List[str] = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(health.router, tags=["Health"])
app.include_router(whatsapp.router, tags=["WhatsApp"])
app.include_router(metrics.router, tags=["Metrics"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )