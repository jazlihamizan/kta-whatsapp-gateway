"""Configuration management for WhatsApp Gateway"""
import os
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
    
    # WhatsApp events (RabbitMQ)
    wa_events_enabled: bool = False
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672/"
    wa_events_exchange: str = "wa.events"

    # Broker settings (deprecated - now using RabbitMQ)
    broker_enabled: bool = False
    broker_api_url: str = "http://127.0.0.1:8000"
    broker_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
