"""WhatsApp service for sending messages via Meta Graph API"""
import httpx
import logging
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Service class for WhatsApp operations."""

    def __init__(self):
        self.base_url = f"https://graph.facebook.com/{settings.meta_graph_api_version}"
        self.phone_number_id = settings.whatsapp_phone_number_id
        self.access_token = settings.whatsapp_access_token
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return a reusable AsyncClient (created lazily)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def send_message(self, to: str, message: str) -> Dict:
        """Send a text message via WhatsApp Cloud API.

        Args:
            to: Recipient phone number in E.164 format (e.g., 6281234567890)
            message: Message text to send

        Returns:
            dict: Response from Meta Graph API

        Raises:
            Exception: If API call fails
        """
        if not self.access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN not configured")

        if not self.phone_number_id:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID not configured")

        url = f"{self.base_url}/{self.phone_number_id}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }

        logger.info(f"Sending message to {to}")

        try:
            client = self._get_client()
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

            result = response.json()
            logger.info(f"Message sent successfully: {result}")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending message: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to send message: {e.response.text}")

        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            raise
