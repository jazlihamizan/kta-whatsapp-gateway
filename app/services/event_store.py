"""Event store service for WhatsApp webhook events.

Provides SQLite-based persistent storage for inbound WhatsApp events.
Stores structured event data WITHOUT sensitive fields (tokens, bearer, api_key, etc.).

This is a supplementary layer — JSONL audit log remains as-is.
"""
import sqlite3
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from contextlib import contextmanager

from app.config import settings

logger = logging.getLogger(__name__)

# Sensitive field names to redact before storage
SENSITIVE_FIELDS = {
    "access_token", "token", "bearer", "authorization",
    "api_key", "apikey", "secret", "password", "verify_token",
}


def _redact_sensitive(data: dict) -> dict:
    """Remove sensitive fields from a dict for safe storage."""
    if not isinstance(data, dict):
        return {}
    result = {}
    for k, v in data.items():
        if k.lower() in SENSITIVE_FIELDS:
            result[k] = "***REDACTED***"
        elif isinstance(v, dict):
            result[k] = _redact_sensitive(v)
        elif isinstance(v, str) and len(v) > 200:
            result[k] = v[:200] + "..."
        else:
            result[k] = v
    return result


def _sanitize_for_json(value) -> str:
    """Serialize value to JSON string, handling non-serializable types."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"error": "serialization_failed"})


class EventStore:
    """SQLite-based event store for WhatsApp webhook events."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.event_store_db_path
        self._ensure_db_dir()
        self._init_schema()

    def _ensure_db_dir(self):
        """Ensure the database directory exists (only if event store is enabled)."""
        if not settings.event_store_enabled:
            return
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_conn(self):
        """Get a SQLite connection with proper cleanup."""
        if not settings.event_store_enabled:
            raise RuntimeError("Event store is disabled")
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize the database schema (only if event store is enabled)."""
        if not settings.event_store_enabled:
            return
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wa_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    phone_number_id TEXT,
                    sender_wa_id TEXT,
                    sender_phone TEXT,
                    message_id TEXT,
                    message_type TEXT,
                    text_body TEXT,
                    routing_key TEXT,
                    publish_status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    raw_event_json TEXT,
                    trace_id TEXT,
                    UNIQUE(event_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_id
                ON wa_events(event_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_publish_status
                ON wa_events(publish_status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sender_phone
                ON wa_events(sender_phone)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_received_at
                ON wa_events(received_at)
            """)
            conn.commit()
            logger.info(f"Event store initialized at {self.db_path}")

    def store_event(
        self,
        event: dict,
        routing_key: Optional[str] = None,
        publish_status: str = "pending",
        error_message: Optional[str] = None,
    ) -> Optional[int]:
        """
        Store a WhatsApp event in the database.

        Args:
            event: Structured event dict from build_wa_event()
            routing_key: RabbitMQ routing key used for this event
            publish_status: One of 'pending', 'published', 'failed'
            error_message: Optional error description if failed

        Returns:
            Database row ID if successful, None if skipped or error
        """
        if not settings.event_store_enabled:
            logger.debug("EVENT_STORE_ENABLED=false, skipping storage")
            return None

        try:
            # Extract core fields from event
            event_id = event.get("event_id", "")
            timestamp = event.get("timestamp", "")
            received_at = datetime.now(timezone.utc).isoformat()
            source = event.get("source", "gateway")
            phone_number_id = event.get("phone_number_id", "")
            sender = event.get("sender", {})
            sender_wa_id = sender.get("wa_id", "")
            sender_phone = sender.get("phone", "")
            message = event.get("message", {})
            message_id = message.get("id", "")
            message_type = message.get("type", "")
            text_body = message.get("text_body", "")
            context = event.get("context", {})
            trace_id = context.get("trace_id", "")

            # Sanitize raw event (remove sensitive fields)
            raw_event_sanitized = _sanitize_for_json(_redact_sensitive(event.copy()))

            with self._get_conn() as conn:
                cursor = conn.execute("""
                    INSERT OR REPLACE INTO wa_events
                    (event_id, timestamp, received_at, source, phone_number_id,
                     sender_wa_id, sender_phone, message_id, message_type, text_body,
                     routing_key, publish_status, error_message, raw_event_json, trace_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event_id,
                    timestamp,
                    received_at,
                    source,
                    phone_number_id,
                    sender_wa_id,
                    sender_phone,
                    message_id,
                    message_type,
                    text_body if text_body else None,
                    routing_key,
                    publish_status,
                    error_message,
                    raw_event_sanitized,
                    trace_id,
                ))
                conn.commit()
                row_id = cursor.lastrowid
                logger.info(f"Event {event_id} stored with status={publish_status}, row_id={row_id}")
                return row_id

        except Exception as e:
            logger.error(f"Failed to store event {event.get('event_id', 'unknown')}: {e}")
            return None

    def update_publish_status(
        self,
        event_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Update the publish status of an event.

        Args:
            event_id: The event ID to update
            status: 'published' or 'failed'
            error_message: Optional error description (only stored for 'failed')

        Returns:
            True if updated, False if not found or error
        """
        if not settings.event_store_enabled:
            return False

        try:
            with self._get_conn() as conn:
                cursor = conn.execute("""
                    UPDATE wa_events
                    SET publish_status = ?, error_message = ?
                    WHERE event_id = ?
                """, (status, error_message, event_id))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"Event {event_id} status updated to {status}")
                    return True
                else:
                    logger.warning(f"Event {event_id} not found for status update")
                    return False

        except Exception as e:
            logger.error(f"Failed to update publish status for {event_id}: {e}")
            return False

    def get_event(self, event_id: str) -> Optional[dict]:
        """Retrieve an event by event_id."""
        if not settings.event_store_enabled:
            return None

        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM wa_events WHERE event_id = ?",
                    (event_id,)
                ).fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Failed to get event {event_id}: {e}")
            return None

    def get_events_by_sender(
        self,
        sender_phone: str,
        limit: int = 100,
    ) -> List[dict]:
        """Get recent events for a sender phone number."""
        if not settings.event_store_enabled:
            return []

        try:
            with self._get_conn() as conn:
                rows = conn.execute("""
                    SELECT * FROM wa_events
                    WHERE sender_phone = ?
                    ORDER BY received_at DESC
                    LIMIT ?
                """, (sender_phone, limit)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get events for sender {sender_phone}: {e}")
            return []

    def get_pending_events(self, limit: int = 100) -> List[dict]:
        """Get events that failed to publish (for retry inspection)."""
        if not settings.event_store_enabled:
            return []

        try:
            with self._get_conn() as conn:
                rows = conn.execute("""
                    SELECT * FROM wa_events
                    WHERE publish_status = 'failed'
                    ORDER BY received_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pending events: {e}")
            return []

    def get_event_count(self) -> int:
        """Get total event count."""
        if not settings.event_store_enabled:
            return 0

        try:
            with self._get_conn() as conn:
                row = conn.execute("SELECT COUNT(*) as count FROM wa_events").fetchone()
                return row["count"] if row else 0
        except Exception:
            return 0


# Global instance
_event_store: Optional[EventStore] = None


def get_event_store() -> EventStore:
    """Get the global event store instance (lazy initialization)."""
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
    return _event_store


def init_event_store() -> EventStore:
    """Initialize and return the global event store instance."""
    global _event_store
    _event_store = EventStore()
    return _event_store


def close_event_store():
    """Close the global event store (no-op for SQLite, but for API consistency)."""
    global _event_store
    _event_store = None