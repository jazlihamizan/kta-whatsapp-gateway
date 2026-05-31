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
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
