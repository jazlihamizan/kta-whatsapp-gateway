# WhatsApp Gateway — Decoupling Contract

**Version:** 1.0-draft  
**Date:** 2026-05-28  
**Status:** DRAFT — for team review  
**Author:** Jazli (Pak Bos) — API Gateway / WhatsApp Gateway  

---

## 1. Overview

Milestone WhatsApp Gateway (local + public webhook + Meta verification + real payload receipt) sudah **PASS**.

Contract ini mendefinisikan interface/event contract yang akan dipublish gateway ke sistem lain setelah decoupling diterapkan. Bukan implementasi — hanya dokumentasi contract untuk disepakati tim.

---

## 2. Gateway Role in Architecture

```
User WhatsApp
    ↓
Meta WhatsApp Cloud API
    ↓
Public API / Webhook (cloudflared + FastAPI)
    ↓
Service API / Gateway (FastAPI — THIS GATEWAY)
    ↓
Decoupling / RabbitMQ / Topic / Publish-Subscribe
    ↓
ADK (main orchestrator)
    ↓
Tools: OCR, data check, retrieval, database
    ↓
AI/OpenSpec (technical specification)
```

**Gateway responsibility:** Menerima payload dari Meta → melakukan validation awal → mempublikasikan event ke message broker (RabbitMQ topic) → sistem lain (ADK/N8N/OpenClaw) consume sebagai consumer.

**Gateway does NOT:** Process business logic, access database, call AI, or make decisions.

---

## 3. Events to Publish

### 3.1 `whatsapp.message.received`

Dipublish setiap kali pesan WhatsApp masuk dari Meta ke `POST /webhook/whatsapp`.

**Topic/Queue suggestion:** `whatsapp.inbound.message`

**Trigger:** Payload masuk ke `POST /webhook/whatsapp` → validated → published.

**Payload (minimal):**

```json
{
  "event_name": "whatsapp.message.received",
  "event_id": "<unique-message-id-from-meta>",
  "timestamp": "<ISO-8601 UTC>",
  "source": "gateway",
  "phone_number_id": "<WA Business phone number ID>",
  "sender": "<E.164 format: 628XXXXXXXXXX>",
  "sender_name": "<contact name if available, else null>",
  "message_type": "<text|image|document|audio|video|sticker|location|contact|interactive>",
  "text_body": "<plain text if message_type=text, else null>",
  "media_url": "<media URL if applicable, else null>",
  "raw_payload_summary": {
    "messaging_product": "whatsapp",
    "display_phone_number": "<WA Business display number>",
    "contact_wa_id": "<sender E.164>"
  }
}
```

**Fields that must NEVER be published:**
- `access_token`
- `WHATSAPP_ACCESS_TOKEN`
- `verify_token`
- Any secret/key/credential

### 3.2 `whatsapp.message.delivery_status` (future-ready)

Dipublish untuk status delivery report dari Meta (optional, jika nanti dipakai).

**Topic/Queue suggestion:** `whatsapp.delivery_status`

**Payload:**

```json
{
  "event_name": "whatsapp.message.delivery_status",
  "event_id": "<unique-id>",
  "timestamp": "<ISO-8601 UTC>",
  "source": "gateway",
  "phone_number_id": "<WA Business phone number ID>",
  "original_message_id": "<wamid.xxx>",
  "delivery_status": "<delivered|read|sent|failed>",
  "recipient": "<E.164>"
}
```

---

## 4. Consumers

| Consumer | Topic(s) | Purpose |
|----------|----------|---------|
| **ADK** (Wafik/Ibnu) | `whatsapp.inbound.message` | Main orchestrator, handle business logic |
| **N8N** (Naja) | `whatsapp.inbound.message` | Workflow automation, notifications |
| **OpenClaw** (Habib) | `whatsapp.inbound.message` | AI agent conversation handling |
| **Future: Backend KTA** | `whatsapp.inbound.message` | Member validation, KTA processing |

Consumers bertanggung jawab untuk own topic subscription dan error handling sendiri.

---

## 5. Validation Rules (Gateway Side)

Sebelum publish, gateway HARUS:

1. **Verify token** — reject if `hub.verify_token` mismatch
2. **Validate payload structure** — reject if missing required fields (`object`, `entry`)
3. **Extract sender** — get `message.from` from payload
4. **Log event** — write to `logs/webhook_events.jsonl` (no secrets)
5. **Respond 200 OK** to Meta immediately — do NOT wait for downstream processing

---

## 6. Error Handling

| Scenario | Gateway Action |
|----------|----------------|
| Invalid verify token | Return 403, do not publish |
| Malformed payload | Return 400, log error, do not publish |
| Message broker unavailable | Return 200 to Meta (ack), log error, retry publish async |
| Unknown message type | Publish with `message_type` set, let consumer decide |

**Principle:** Gateway always responds 200 to Meta within timeout. Downstream failures do not affect Meta webhook acknowledgment.

---

## 7. Out of Scope (This Contract)

- ❌ RabbitMQ installation/configuration
- ❌ Consumer implementation
- ❌ OCR KTP
- ❌ KTA generator
- ❌ Admin panel
- ❌ Database integration
- ❌ N8N workflow
- ❌ ADK logic
- ❌ OpenClaw agent logic
- ❌ Deploy to VPS

---

## 8. Next Steps After Contract

1. **Team review** — ADK (Wafik/Ibnu), N8N (Naja), OpenClaw (Habib) setujui contract
2. **ADK team** prepare consumer untuk `whatsapp.inbound.message`
3. **Mas Mamat** prepare RabbitMQ instance (not yet — for future)
4. **Jazli (Pak Bos)** implement publish logic di gateway setelah RabbitMQ ready

---

## 9. Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0-draft | 2026-05-28 | Initial draft |

---

**For questions:** Ask Jazli (Pak Bos) — API Gateway owner