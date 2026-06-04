"""Prometheus metrics for KTA WhatsApp Gateway.

WA-specific observability metrics — no sensitive data in labels.
"""
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY

# ── Webhook reception ────────────────────────────────────────────────────────

WEBHOOK_RECEIVED = Counter(
    "wa_gateway_webhook_received_total",
    "Incoming webhook POST to /webhook/whatsapp",
    ["message_type"],  # text, image, audio, video, document, sticker, interactive, unknown
)

# ── Signature verification ───────────────────────────────────────────────────

SIGNATURE_VERIFICATION = Counter(
    "wa_gateway_signature_verification_total",
    "X-Hub-Signature-256 verification outcomes",
    ["status"],  # valid, invalid, missing, disabled
)

# ── Rate limiting ─────────────────────────────────────────────────────────────

RATE_LIMITED = Counter(
    "wa_gateway_rate_limited_total",
    "Requests blocked by rate limiter",
    ["endpoint"],  # webhook, send_message
)

# ── RabbitMQ publish ──────────────────────────────────────────────────────────

PUBLISH_TOTAL = Counter(
    "wa_gateway_publish_total",
    "RabbitMQ publish attempts for WA events",
    ["status", "routing_key"],  # published, failed | wa.inbound.text, wa.inbound.interactive, etc.
)

PUBLISH_LATENCY = Histogram(
    "wa_gateway_publish_latency_seconds",
    "Time spent in rabbitmq_publisher.publish()",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0),
)

# ── Event store ───────────────────────────────────────────────────────────────

EVENT_STORE_WRITES = Counter(
    "wa_gateway_event_store_writes_total",
    "SQLite event store write operations",
    ["operation", "status"],  # store, update | success, failure
)


def get_metrics() -> bytes:
    """Generate Prometheus text format metrics."""
    return generate_latest(REGISTRY)


def get_content_type() -> str:
    """Return the Prometheus content type string."""
    return CONTENT_TYPE_LATEST