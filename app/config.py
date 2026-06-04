"""Configuration management for WhatsApp Gateway"""
import os
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # App settings
    app_name: str = "KTA WhatsApp Gateway"
    debug: bool = False

    # WhatsApp settings
    whatsapp_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    meta_graph_api_version: str = "v21.0"

    # WhatsApp App Secret for X-Hub-Signature-256 verification
    whatsapp_signature_verify_enabled: bool = False
    whatsapp_app_secret: str = ""

    # RabbitMQ WhatsApp Events
    wa_events_enabled: bool = False
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672/"
    wa_events_exchange: str = "wa.events"

    # CORS settings
    cors_allow_origins: str = "*"  # comma-separated or "*"

    # Rate limiting
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ALLOW_ORIGINS into a list."""
        val = self.cors_allow_origins.strip()
        if val == "*":
            return ["*"]
        return [origin.strip() for origin in val.split(",") if origin.strip()]


# Global settings instance
settings = Settings()