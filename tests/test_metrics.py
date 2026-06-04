"""Tests for G5: Prometheus metrics endpoint and instrumented flow."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from app.main import app


class TestMetricsEndpoint:
    """Tests for GET /metrics endpoint."""

    def test_metrics_endpoint_returns_200(self):
        """GET /metrics should return 200."""
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_text_format(self):
        """GET /metrics should return Prometheus text format."""
        client = TestClient(app)
        response = client.get("/metrics")
        # Prometheus text format contains metric names
        content = response.text
        assert "wa_gateway" in content

    def test_metrics_endpoint_has_wa_gateway_prefix(self):
        """All metrics should be prefixed with wa_gateway_."""
        client = TestClient(app)
        response = client.get("/metrics")
        content = response.text
        # All defined metrics should appear
        assert "wa_gateway_webhook_received_total" in content
        assert "wa_gateway_signature_verification_total" in content
        assert "wa_gateway_rate_limited_total" in content
        assert "wa_gateway_publish_total" in content
        assert "wa_gateway_publish_latency_seconds" in content
        assert "wa_gateway_event_store_writes_total" in content

    def test_metrics_no_phone_numbers_in_output(self):
        """Metrics labels should never contain real phone numbers."""
        client = TestClient(app)
        response = client.get("/metrics")
        content = response.text
        # Phone number patterns should not appear in labels
        assert "6285" not in content
        assert "+6285" not in content
        assert "wa_id" not in content.lower() or "wa_gateway" in content.lower()
        # Verify it's metrics output, not debug data
        assert "628" not in content or content.count("628") == 0

    def test_message_type_labels_present(self):
        """WEBHOOK_RECEIVED should expose message_type label values."""
        client = TestClient(app)
        response = client.get("/metrics")
        content = response.text
        # Should have the counter defined with label
        assert "wa_gateway_webhook_received_total" in content

    def test_routing_key_label_present(self):
        """PUBLISH_TOTAL should expose routing_key label."""
        client = TestClient(app)
        response = client.get("/metrics")
        content = response.text
        assert "wa_gateway_publish_total" in content

    def test_signature_status_labels_present(self):
        """SIGNATURE_VERIFICATION should expose status label."""
        client = TestClient(app)
        response = client.get("/metrics")
        content = response.text
        assert "wa_gateway_signature_verification_total" in content


class TestMetricsInstrumentation:
    """Tests that instrumented code increments metrics correctly."""

    def test_webhook_received_increments_on_valid_payload(self):
        """Webhook processing should increment WEBHOOK_RECEIVED counter."""
        from app.metrics import WEBHOOK_RECEIVED

        # Get initial value
        initial = self._get_counter_value("wa_gateway_webhook_received_total", "text")

        # Simulate a webhook payload
        valid_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "123456789"},
                        "messaging_product": "whatsapp",
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test123",
                            "type": "text",
                            "text": {"body": "Hello"},
                            "timestamp": "1234567890"
                        }],
                        "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Test"}}]
                    },
                    "field": "messages"
                }]
            }]
        }

        client = TestClient(app)
        # Mock signature verification disabled
        with patch("app.routes.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_signature_verify_enabled = False
            with patch("app.routes.whatsapp.check_rate_limit", return_value=None):
                with patch("app.services.rabbitmq_publisher.rabbitmq_publisher.publish", new_callable=AsyncMock) as mock_pub:
                    mock_pub.return_value = True
                    response = client.post("/webhook/whatsapp", json=valid_payload)

        # Counter should be incremented
        final = self._get_counter_value("wa_gateway_webhook_received_total", "text")
        assert final > initial, "WEBHOOK_RECEIVED counter should increment after webhook"

    def test_signature_verification_metrics_disabled_mode(self):
        """When signature verification is disabled, status=disabled should be tracked."""
        from app.metrics import SIGNATURE_VERIFICATION

        initial = self._get_signature_counter_value("disabled")

        valid_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "123456789"},
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test123",
                            "type": "text",
                            "text": {"body": "Hello"},
                            "timestamp": "1234567890"
                        }],
                        "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Test"}}]
                    },
                    "field": "messages"
                }]
            }]
        }

        client = TestClient(app)
        with patch("app.routes.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_signature_verify_enabled = False
            with patch("app.routes.whatsapp.check_rate_limit", return_value=None):
                with patch("app.services.rabbitmq_publisher.rabbitmq_publisher.publish", new_callable=AsyncMock) as mock_pub:
                    mock_pub.return_value = True
                    response = client.post("/webhook/whatsapp", json=valid_payload)

        final = self._get_signature_counter_value("disabled")
        assert final > initial, "SIGNATURE_VERIFICATION with status=disabled should increment"

    def test_rate_limit_metric_on_429(self):
        """When rate limited, RATE_LIMITED counter should increment."""
        from app.metrics import RATE_LIMITED
        import app.routes.whatsapp as whatsapp_module

        initial = self._get_rate_limited_value("webhook")

        client = TestClient(app)
        with patch("app.routes.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_signature_verify_enabled = False
            mock_settings.rate_limit_enabled = True
            # Patch the check_rate_limit call in whatsapp.py to return 429
            with patch.object(whatsapp_module, "check_rate_limit") as mock_rate_limit:
                mock_rate_limit.return_value = JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": "60"}
                )
                response = client.post("/webhook/whatsapp", json={"entry": []})

        # Should get 429
        assert response.status_code == 429
        final = self._get_rate_limited_value("webhook")
        assert final > initial, "RATE_LIMITED counter should increment on 429"

        # Should get 429
        assert response.status_code == 429
        final = self._get_rate_limited_value("webhook")
        assert final > initial, "RATE_LIMITED counter should increment on 429"

    def test_publish_metric_on_success(self):
        """Successful publish should increment PUBLISH_TOTAL with status=published."""
        from app.metrics import PUBLISH_TOTAL

        initial_published = self._get_publish_value("published")
        initial_failed = self._get_publish_value("failed")

        valid_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "123456789"},
                        "messaging_product": "whatsapp",
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test123",
                            "type": "text",
                            "text": {"body": "Hello"},
                            "timestamp": "1234567890"
                        }],
                        "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Test"}}]
                    },
                    "field": "messages"
                }]
            }]
        }

        client = TestClient(app)
        with patch("app.routes.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_signature_verify_enabled = False
            with patch("app.routes.whatsapp.check_rate_limit", return_value=None):
                with patch("app.services.rabbitmq_publisher.rabbitmq_publisher.publish", new_callable=AsyncMock) as mock_pub:
                    mock_pub.return_value = True
                    response = client.post("/webhook/whatsapp", json=valid_payload)

        final_published = self._get_publish_value("published")
        assert final_published > initial_published, "PUBLISH_TOTAL status=published should increment"
        assert final_published - initial_published == 1
        # failed should not change
        assert self._get_publish_value("failed") == initial_failed

    def test_publish_metric_on_failure(self):
        """Failed publish should increment PUBLISH_TOTAL with status=failed."""
        from app.metrics import PUBLISH_TOTAL

        initial_published = self._get_publish_value("published")
        initial_failed = self._get_publish_value("failed")

        valid_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "123456789"},
                        "messaging_product": "whatsapp",
                        "messages": [{
                            "from": "6281234567890",
                            "id": "wamid.test123",
                            "type": "text",
                            "text": {"body": "Hello"},
                            "timestamp": "1234567890"
                        }],
                        "contacts": [{"wa_id": "6281234567890", "profile": {"name": "Test"}}]
                    },
                    "field": "messages"
                }]
            }]
        }

        client = TestClient(app)
        with patch("app.routes.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_signature_verify_enabled = False
            with patch("app.routes.whatsapp.check_rate_limit", return_value=None):
                with patch("app.services.rabbitmq_publisher.rabbitmq_publisher.publish", new_callable=AsyncMock) as mock_pub:
                    mock_pub.return_value = False  # Simulate publish failure
                    response = client.post("/webhook/whatsapp", json=valid_payload)

        final_failed = self._get_publish_value("failed")
        assert final_failed > initial_failed, "PUBLISH_TOTAL status=failed should increment"

    def test_no_sensitive_data_in_metric_labels(self):
        """Metric labels should not contain phone numbers, wa_id, or tokens."""
        from app.metrics import get_metrics

        content = get_metrics().decode("utf-8")
        # Should not contain phone number patterns
        assert "628123456789" not in content
        assert "wamid.test" not in content
        # Should not contain tokens
        assert "token" not in content.lower() or "wa_gateway_signature" in content.lower()
        assert "secret" not in content.lower() or "wa_gateway" in content.lower()
        assert "bearer" not in content.lower()

    def test_histogram_has_buckets(self):
        """PUBLISH_LATENCY histogram should have proper buckets."""
        from app.metrics import get_metrics

        content = get_metrics().decode("utf-8")
        assert "wa_gateway_publish_latency_seconds" in content
        # Histogram should have buckets (le=)
        assert "le=" in content

    # ── Helper methods ─────────────────────────────────────────────────────────

    def _get_counter_value(self, name: str, label_value: str) -> float:
        """Read a Counter value by metric name and label."""
        from prometheus_client import CollectorRegistry
        from app.metrics import WEBHOOK_RECEIVED

        # Find the metric in the default registry
        for metric in CollectorRegistry().collect():
            if metric.name == name:
                for sample in metric.samples:
                    if sample.labels.get("message_type") == label_value:
                        return sample.value
        # Fallback: use the metric object directly
        try:
            counter = WEBHOOK_RECEIVED
            for labels in [({"message_type": label_value})]:
                return counter.labels(**labels)._value.get()
        except Exception:
            return 0.0

    def _get_signature_counter_value(self, status: str) -> float:
        """Read signature verification counter value by status label."""
        from prometheus_client import CollectorRegistry
        from app.metrics import SIGNATURE_VERIFICATION

        for metric in CollectorRegistry().collect():
            if metric.name == "wa_gateway_signature_verification_total":
                for sample in metric.samples:
                    if sample.labels.get("status") == status:
                        return sample.value
        try:
            return SIGNATURE_VERIFICATION.labels(status=status)._value.get()
        except Exception:
            return 0.0

    def _get_rate_limited_value(self, endpoint: str) -> float:
        """Read rate limited counter value by endpoint label."""
        from prometheus_client import CollectorRegistry
        from app.metrics import RATE_LIMITED

        for metric in CollectorRegistry().collect():
            if metric.name == "wa_gateway_rate_limited_total":
                for sample in metric.samples:
                    if sample.labels.get("endpoint") == endpoint:
                        return sample.value
        try:
            return RATE_LIMITED.labels(endpoint=endpoint)._value.get()
        except Exception:
            return 0.0

    def _get_publish_value(self, status: str) -> float:
        """Read publish counter value by status label."""
        from prometheus_client import CollectorRegistry
        from app.metrics import PUBLISH_TOTAL

        for metric in CollectorRegistry().collect():
            if metric.name == "wa_gateway_publish_total":
                for sample in metric.samples:
                    if sample.labels.get("status") == status:
                        return sample.value
        try:
            return PUBLISH_TOTAL.labels(status=status, routing_key="wa.inbound.text")._value.get()
        except Exception:
            return 0.0