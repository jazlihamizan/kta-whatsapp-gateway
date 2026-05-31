# KTA WhatsApp Gateway

API Gateway untuk integrasi WhatsApp Cloud API dengan sistem KTA Partai UMMAT.

## ✅ Milestone Status — 2026-05-28

**WhatsApp Gateway (Phase 1): COMPLETE**

| Checkpoint | Status |
|------------|--------|
| Local gateway (FastAPI port 8000) | ✅ PASS |
| Public webhook via cloudflared | ✅ PASS |
| Meta webhook verification | ✅ PASS |
| messages field subscribed | ✅ PASS |
| Real WhatsApp payload received | ✅ PASS |

**Bukti real payload** (dari `logs/webhook_events.jsonl`):
- sender: `6285721631961`
- text: `halo ini test real webhook dari pakbos`
- timestamp: `2026-05-28T00:38:54+00:00`

**Contract untuk decoupling:** `docs/whatsapp_gateway_decoupling_contract.md`

---

- Mengirim pesan WhatsApp
- Routing pesan ke sistem lain

## 🚀 Fitur

- ✅ Health check endpoint
- ✅ Webhook verification untuk Meta
- ✅ Receive incoming WhatsApp messages
- ✅ Send WhatsApp messages via Meta Graph API
- ✅ Logging dan error handling
- ✅ Environment-based configuration
- ✅ Unit tests

## 📦 Tech Stack

- **FastAPI** - Modern Python web framework
- **Pydantic** - Data validation
- **httpx** - Async HTTP client
- **pytest** - Testing framework
- **uvicorn** - ASGI server

## 🛠️ Installation

### 1. Clone atau buat project directory

```bash
cd C:\Users\jazli\.openclaw\workspace\projects\kta-whatsapp-gateway
```

### 2. Buat virtual environment

```bash
python -m venv venv
```

### 3. Activate virtual environment

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Setup environment variables

Copy `.env.example` ke `.env`:

```bash
copy .env.example .env
```

Edit `.env` dan isi dengan credential Meta WhatsApp:

```env
WHATSAPP_VERIFY_TOKEN=your_verify_token_here
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
META_GRAPH_API_VERSION=v21.0
```

## 🔑 Mendapatkan Credentials

### WhatsApp Verify Token
- Buat token random sendiri (misalnya: `my_secure_token_123`)
- Token ini akan digunakan untuk verifikasi webhook di Meta Developer Console

### WhatsApp Access Token
- Login ke [Meta for Developers](https://developers.facebook.com/)
- Buat atau pilih App
- Pilih WhatsApp > API Setup
- Copy **Temporary Access Token** atau generate **Permanent Token**

### Phone Number ID
- Di halaman WhatsApp API Setup
- Lihat section **Phone Number ID**
- Copy ID tersebut

## 🏃 Running the Server

### Development mode (with auto-reload)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production mode

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Server akan berjalan di: `http://localhost:8000`

## 📚 API Documentation

Setelah server running, buka:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🧪 Testing

### Run all tests

```bash
pytest
```

### Run with coverage

```bash
pytest --cov=app tests/
```

### Run specific test file

```bash
pytest tests/test_health.py
pytest tests/test_whatsapp_webhook.py
```

## 📡 API Endpoints

### 1. Health Check

**GET** `/health`

Response:
```json
{
  "status": "ok",
  "service": "KTA WhatsApp Gateway",
  "version": "0.1.0"
}
```

### 2. Webhook Verification (Meta)

**GET** `/webhook/whatsapp`

Query Parameters:
- `hub.mode`: "subscribe"
- `hub.verify_token`: Your verify token
- `hub.challenge`: Challenge string from Meta

Response: Returns challenge number if verification succeeds

### 3. Receive Webhook (Incoming Messages)

**POST** `/webhook/whatsapp`

Receives incoming WhatsApp messages from Meta.

Request body: Meta webhook payload (JSON)

Response:
```json
{
  "status": "ok"
}
```

### 4. Send Message

**POST** `/send-message`

Send a WhatsApp message.

Request body:
```json
{
  "to": "6281234567890",
  "message": "Hello from KTA Gateway!"
}
```

Response:
```json
{
  "status": "success",
  "message_id": "wamid.HBgLNjI4MTIzNDU2Nzg5MBUCABIYFjNFQjBDMUQxRjg5QzRGNEE4RjAw"
}
```

## 🔧 Configuration

Edit `app/config.py` atau set environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `WHATSAPP_VERIFY_TOKEN` | Token untuk verifikasi webhook | - |
| `WHATSAPP_ACCESS_TOKEN` | Meta access token | - |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID | - |
| `META_GRAPH_API_VERSION` | Meta Graph API version | v21.0 |
| `DEBUG` | Debug mode | false |

## 🔒 Security

- ✅ Credentials disimpan di `.env` (tidak di-commit ke git)
- ✅ `.env` sudah masuk `.gitignore`
- ✅ Token verification untuk webhook
- ✅ Error handling dan logging

**JANGAN:**
- Commit `.env` ke git
- Share access token di chat/dokumentasi
- Hardcode credentials di code

## 📁 Project Structure

```
kta-whatsapp-gateway/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration management
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py        # Health check endpoint
│   │   └── whatsapp.py      # WhatsApp endpoints
│   ├── services/
│   │   ├── __init__.py
│   │   └── whatsapp_service.py  # WhatsApp API service
│   └── schemas/
│       ├── __init__.py
│       └── whatsapp.py      # Pydantic schemas
├── tests/
│   ├── __init__.py
│   ├── test_health.py
│   └── test_whatsapp_webhook.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## 🚧 Next Steps (Out of Scope untuk sekarang)

- [ ] OCR KTP
- [ ] Generate KTA
- [ ] Admin approval system
- [ ] Dashboard admin
- [ ] Database integration
- [ ] OpenClaw agent integration
- [ ] N8N workflow integration
- [ ] Deploy ke VPS

## 👥 Team

- **Jazli (Pak Bos)**: API Gateway / WhatsApp Gateway
- **Habib**: OpenClaw
- **Naja**: N8N
- **Wafik/Ibnu**: ADK / Laravel Filament
- **Zaky**: PM
- **Mas Mamat**: Server / Infra

## 📝 License

Internal project - KTA Partai UMMAT

## 🆘 Troubleshooting

### Error: "WHATSAPP_VERIFY_TOKEN not set"
- Pastikan file `.env` sudah dibuat
- Pastikan `WHATSAPP_VERIFY_TOKEN` sudah diisi

### Error: "Failed to send message"
- Cek `WHATSAPP_ACCESS_TOKEN` valid
- Cek `WHATSAPP_PHONE_NUMBER_ID` benar
- Cek nomor tujuan format E.164 (contoh: 6281234567890)

### Webhook verification gagal
- Pastikan `WHATSAPP_VERIFY_TOKEN` di `.env` sama dengan yang di Meta Developer Console
- Cek logs untuk detail error
