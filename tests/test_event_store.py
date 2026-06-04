"""Tests for event store service (G1: SQLite persistence)"""
import pytest
import os
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.event_store import (
    EventStore,
    _redact_sensitive,
    get_event_store,
    init_event_store,
    close_event_store,
)
from app.config import settings


class TestRedactSensitive:
    """Tests for sensitive data redaction."""

    def test_redact_access_token(self):
        data = {"access_token": "super_secret_12345", "message": "hello"}
        result = _redact_sensitive(data)
        assert result["access_token"] == "***REDACTED***"
        assert result["message"] == "hello"

    def test_redact_bearer_token(self):
        data = {"bearer": "token_abc", "text": "test"}
        result = _redact_sensitive(data)
        assert result["bearer"] == "***REDACTED***"
        assert result["text"] == "test"

    def test_redact_authorization(self):
        data = {"authorization": "Bearer xyz", "data": "value"}
        result = _redact_sensitive(data)
        assert result["authorization"] == "***REDACTED***"
        assert result["data"] == "value"

    def test_redact_api_key(self):
        data = {"api_key": "key_12345", "content": "text"}
        result = _redact_sensitive(data)
        assert result["api_key"] == "***REDACTED***"
        assert result["content"] == "text"

    def test_redact_nested(self):
        data = {"outer": {"access_token": "nested_secret", "inner": "value"}}
        result = _redact_sensitive(data)
        assert result["outer"]["access_token"] == "***REDACTED***"
        assert result["outer"]["inner"] == "value"

    def test_no_redact_safe_fields(self):
        data = {"phone": "6281234567890", "message_type": "text", "sender_name": "Test"}
        result = _redact_sensitive(data)
        assert result["phone"] == "6281234567890"
        assert result["message_type"] == "text"
        assert result["sender_name"] == "Test"


class TestEventStoreSchema:
    """Tests for event store schema initialization."""

    @pytest.fixture(autouse=True)
    def enable_store(self):
        """Enable event store for all tests in this class."""
        with patch.object(settings, "event_store_enabled", True):
            yield

    def test_init_creates_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            # Check table exists
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wa_events'"
            )
            row = cursor.fetchone()
            conn.close()

            assert row is not None
            assert row[0] == "wa_events"

    def test_init_creates_indexes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='wa_events'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert "idx_event_id" in indexes
            assert "idx_publish_status" in indexes
            assert "idx_sender_phone" in indexes
            assert "idx_received_at" in indexes


class TestEventStoreCRUD:
    """Tests for event store insert/update operations."""

    @pytest.fixture(autouse=True)
    def enable_store(self):
        """Enable event store for all tests in this class."""
        with patch.object(settings, "event_store_enabled", True):
            yield

    def test_store_event_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            event = {
                "event_id": "evt_test001",
                "event_name": "whatsapp.message.received",
                "timestamp": "2024-01-01T00:00:00.000000+00:00",
                "source": "gateway",
                "phone_number_id": "123456789",
                "sender": {
                    "phone": "6280000000000",
                    "wa_id": "6280000000000",
                    "name": "Test User",
                },
                "message": {
                    "id": "wamid.test001",
                    "type": "text",
                    "text_body": "Halo dunia",
                    "timestamp": 1234567890,
                },
                "context": {"trace_id": "gw-20240101000000"},
            }

            row_id = store.store_event(event, routing_key="wa.inbound.text", publish_status="pending")
            assert row_id is not None

            # Verify stored
            stored = store.get_event("evt_test001")
            assert stored is not None
            assert stored["event_id"] == "evt_test001"
            assert stored["publish_status"] == "pending"
            assert stored["message_type"] == "text"
            assert stored["text_body"] == "Halo dunia"
            assert stored["routing_key"] == "wa.inbound.text"

    def test_store_event_sanitizes_raw_json(self):
        """Raw event JSON should have sensitive fields redacted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            event = {
                "event_id": "evt_test002",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "source": "gateway",
                "phone_number_id": "123456789",
                "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                "message": {"id": "wamid.test002", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                "context": {"trace_id": "gw-001"},
                "access_token": "should_be_redacted",  # sensitive
            }

            row_id = store.store_event(event, routing_key="wa.inbound.text")
            stored = store.get_event("evt_test002")
            raw_json = stored["raw_event_json"]

            assert "should_be_redacted" not in raw_json
            assert "***REDACTED***" in raw_json

    def test_update_publish_status_published(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            event = {
                "event_id": "evt_test003",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "source": "gateway",
                "phone_number_id": "123456789",
                "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                "message": {"id": "wamid.test003", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                "context": {"trace_id": "gw-003"},
            }

            store.store_event(event, publish_status="pending")
            result = store.update_publish_status("evt_test003", "published")

            assert result is True
            updated = store.get_event("evt_test003")
            assert updated["publish_status"] == "published"
            assert updated["error_message"] is None

    def test_update_publish_status_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            event = {
                "event_id": "evt_test004",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "source": "gateway",
                "phone_number_id": "123456789",
                "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                "message": {"id": "wamid.test004", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                "context": {"trace_id": "gw-004"},
            }

            store.store_event(event, publish_status="pending")
            result = store.update_publish_status(
                "evt_test004", "failed", error_message="RabbitMQ connection refused"
            )

            assert result is True
            updated = store.get_event("evt_test004")
            assert updated["publish_status"] == "failed"
            assert "RabbitMQ connection refused" in updated["error_message"]

    def test_get_events_by_sender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            for i in range(5):
                event = {
                    "event_id": f"evt_sender_{i}",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "source": "gateway",
                    "phone_number_id": "123456789",
                    "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                    "message": {"id": f"wamid.s_{i}", "type": "text", "text_body": f"Test {i}", "timestamp": 1234567890},
                    "context": {"trace_id": f"gw-s_{i}"},
                }
                store.store_event(event)

            events = store.get_events_by_sender("6280000000000", limit=3)
            assert len(events) == 3
            assert all(e["sender_phone"] == "6280000000000" for e in events)

    def test_get_pending_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            for i in range(3):
                event = {
                    "event_id": f"evt_pending_{i}",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "source": "gateway",
                    "phone_number_id": "123456789",
                    "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                    "message": {"id": f"wamid.p_{i}", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                    "context": {"trace_id": f"gw-p_{i}"},
                }
                # First 2 stored as pending, then updated to failed
                store.store_event(event, publish_status="pending")
                if i < 2:
                    store.update_publish_status(f"evt_pending_{i}", "failed", error_message="Test failure")

            pending = store.get_pending_events()
            assert len(pending) == 2
            assert all(e["publish_status"] == "failed" for e in pending)

    def test_get_event_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = EventStore(db_path=db_path)

            for i in range(7):
                event = {
                    "event_id": f"evt_count_{i}",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "source": "gateway",
                    "phone_number_id": "123456789",
                    "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                    "message": {"id": f"wamid.c_{i}", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                    "context": {"trace_id": f"gw-c_{i}"},
                }
                store.store_event(event)

            count = store.get_event_count()
            assert count == 7

    def test_store_event_disabled_returns_none(self):
        """When EVENT_STORE_ENABLED=false, store_event should return None."""
        with patch.object(settings, "event_store_enabled", False):
            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = os.path.join(tmpdir, "test.db")
                store = EventStore(db_path=db_path)

                event = {
                    "event_id": "evt_disabled",
                    "timestamp": "2024-01-01T00:00:00+00:00",
                    "source": "gateway",
                    "phone_number_id": "123456789",
                    "sender": {"phone": "6280000000000", "wa_id": "", "name": ""},
                    "message": {"id": "wamid.d", "type": "text", "text_body": "Test", "timestamp": 1234567890},
                    "context": {"trace_id": "gw-d"},
                }

                result = store.store_event(event, routing_key="wa.inbound.text", publish_status="pending")
                assert result is None


class TestEventStoreGlobalInstance:
    """Tests for global event store singleton."""

    def test_init_and_get_singleton(self):
        """get_event_store should return the same instance."""
        close_event_store()  # reset

        with patch.object(settings, "event_store_db_path", ":memory:"):
            store1 = get_event_store()
            store2 = get_event_store()
            assert store1 is store2

        close_event_store()

    def test_close_clears_instance(self):
        """close_event_store should clear the singleton."""
        close_event_store()

        with patch.object(settings, "event_store_db_path", ":memory:"):
            store1 = get_event_store()
            close_event_store()
            store2 = get_event_store()
            assert store1 is not store2

        close_event_store()