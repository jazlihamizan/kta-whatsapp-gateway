"""KTA WhatsApp Gateway - Main FastAPI Application"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import health, whatsapp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="KTA WhatsApp Gateway",
    description="API Gateway for WhatsApp Cloud API integration with KTA Partai UMMAT system",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware (configure as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(whatsapp.router, tags=["WhatsApp"])


@app.on_event("startup")
async def startup_event():
    """Application startup event"""
    logger.info("Starting KTA WhatsApp Gateway...")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"Meta Graph API version: {settings.meta_graph_api_version}")

    # Verify critical settings
    if not settings.whatsapp_verify_token:
        logger.warning("WHATSAPP_VERIFY_TOKEN not set - webhook verification will fail")

    if not settings.whatsapp_access_token:
        logger.warning("WHATSAPP_ACCESS_TOKEN not set - sending messages will fail")

    if not settings.whatsapp_phone_number_id:
        logger.warning("WHATSAPP_PHONE_NUMBER_ID not set - sending messages will fail")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event"""
    logger.info("Shutting down KTA WhatsApp Gateway...")
    await whatsapp.whatsapp_service.close()
    from app.services.rabbitmq_publisher import rabbitmq_publisher
    await rabbitmq_publisher.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
