py -3.12 --version# WhatBot AI — WhatsApp AI Auto Reply

A production-ready WhatsApp AI auto-reply system. Connect your WhatsApp account, configure an AI persona, and automatically respond to customer messages using Google Gemini.

---

## Features

- **Real WhatsApp connection** via Neonize (QR code scan)
- **AI auto-reply** powered by Google Gemini
- **Human takeover** — pause AI for any conversation
- **Real-time dashboard** via WebSocket
- **Multi-account** support
- **API key system** — integrate with your own apps
- **Dark/light mode**
- **Secure** — JWT auth, hashed API keys, no secrets in frontend

---

## Requirements

- Docker & Docker Compose
- Google Gemini API key ([get one here](https://aistudio.google.com/app/apikey))
- A smartphone with WhatsApp installed

---

## Quick Start (Docker)

### 1. Clone and configure

```bash
git clone <repo>
cd whatsapp-ai
cp .env.example .env
```

### 2. Edit `.env`

```env
GEMINI_API_KEY=your_actual_gemini_api_key
JWT_SECRET=a_very_long_random_secret_string
SESSION_ENCRYPTION_KEY=another_32_char_secret_string____
```

### 3. Start everything

```bash
docker compose up --build
```

This starts:
| Service | Port |
|---|---|
| Frontend (Next.js) | http://localhost:3000 |
| Backend (FastAPI) | http://localhost:8000 |
| WhatsApp Worker | — |
| PostgreSQL | 5432 |
| Redis | 6379 |
| Nginx proxy | http://localhost:80 |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ | — | Google Gemini API key |
| `GEMINI_MODEL` | | `gemini-1.5-flash` | Gemini model name |
| `JWT_SECRET` | ✅ | — | JWT signing secret (use random 64+ chars) |
| `SESSION_ENCRYPTION_KEY` | ✅ | — | WhatsApp session encryption key |
| `DATABASE_URL` | | auto-set in Docker | PostgreSQL connection string |
| `REDIS_URL` | | auto-set in Docker | Redis connection string |
| `CORS_ORIGINS` | | `http://localhost:3000` | Allowed frontend origins |
| `SESSIONS_DIR` | | `/app/sessions` | Path to store WhatsApp sessions |

---

## Database

Tables are created automatically on startup via SQLAlchemy.

### Manual setup (local dev)

```bash
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql://... python -c "from app.database.database import create_tables; create_tables()"
```

---

## Running Locally (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values

# Start API server
uvicorn app.main:app --reload --port 8000

# In a separate terminal - start the WhatsApp worker
python -m workers.whatsapp_worker
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_URL

npm run dev
```

Open http://localhost:3000

---

## Connecting WhatsApp

1. Register/login at http://localhost:3000
2. Navigate to **WhatsApp Accounts**
3. Click **+ Add Account** and give it a name
4. A QR code will appear
5. Open WhatsApp on your phone
6. Go to **Settings → Linked Devices → Link a Device**
7. Scan the QR code
8. Wait for "✓ WhatsApp Connected"

Sessions are persisted to disk. You won't need to scan again unless you explicitly disconnect or delete the account.

---

## Configuring Gemini

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create an API key
3. Set it in your `.env` file as `GEMINI_API_KEY`
4. Optionally change the model: `GEMINI_MODEL=gemini-1.5-pro`

### Customize AI behavior

Go to **Settings** in the dashboard:
- Toggle AI on/off per account
- Change the system prompt
- Set reply language
- Set max reply length
- Toggle group chat replies

---

## API Documentation

Interactive docs: http://localhost:8000/docs

### Authentication

All endpoints (except health and public API) require a JWT token:

```
Authorization: Bearer <jwt_token>
```

### Key Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register user |
| `POST` | `/api/auth/login` | Login |
| `GET` | `/api/whatsapp/accounts` | List accounts |
| `POST` | `/api/whatsapp/accounts` | Create account |
| `GET` | `/api/whatsapp/accounts/{id}/qr` | Get QR code |
| `GET` | `/api/conversations` | List conversations |
| `GET` | `/api/conversations/{id}/messages` | Get messages |
| `POST` | `/api/messages/send` | Send message |
| `GET/PUT` | `/api/bot/settings/{account_id}` | Bot settings |
| `POST` | `/api/api-keys` | Create API key |
| `GET` | `/api/dashboard/stats` | Dashboard stats |
| `GET` | `/api/health` | Health check |

### Public API (API Key auth)

Send messages from your own application:

```bash
curl -X POST http://localhost:8000/api/v1/messages/send \
  -H "Authorization: Bearer wha_live_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "your-account-uuid",
    "phone": "919876543210",
    "message": "Hello from my app!"
  }'
```

---

## WebSocket Events

Connect to `ws://localhost:8000/ws/<jwt_token>` for real-time updates.

| Event | Description | Payload |
|---|---|---|
| `qr_updated` | New QR code available | `{account_id, qr_code, status}` |
| `account_connected` | WhatsApp connected | `{account_id, phone_number}` |
| `account_disconnected` | WhatsApp disconnected | `{account_id}` |
| `message_received` | Incoming message | `{id, conversation_id, content, sender}` |
| `message_sent` | Outgoing message sent | `{id, conversation_id, content}` |
| `ai_reply_started` | AI generating reply | `{conversation_id}` |
| `ai_reply_completed` | AI reply ready | `{id, conversation_id, content}` |

---

## Project Structure

```
whatsapp-ai/
├── frontend/                   # Next.js 14 app
│   ├── app/
│   │   ├── login/              # Login/Register page
│   │   ├── dashboard/          # Main dashboard
│   │   ├── whatsapp/           # Account management + QR
│   │   ├── conversations/      # Chat interface
│   │   ├── settings/           # Bot configuration
│   │   └── api-keys/           # API key management
│   ├── components/
│   │   └── layout/Sidebar.tsx  # Navigation sidebar
│   ├── hooks/
│   │   └── useWebSocket.ts     # Real-time WS hook
│   ├── lib/
│   │   ├── api.ts              # Axios API client
│   │   ├── auth-context.tsx    # Auth state
│   │   └── utils.ts            # Helpers
│   └── types/index.ts          # TypeScript types
│
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app + WebSocket
│   │   ├── config.py           # Settings from env
│   │   ├── api/                # Route handlers
│   │   │   ├── auth.py
│   │   │   ├── whatsapp.py
│   │   │   ├── conversations.py
│   │   │   ├── messages.py
│   │   │   ├── bot.py
│   │   │   ├── api_keys.py
│   │   │   ├── dashboard.py
│   │   │   └── public.py
│   │   ├── models/models.py    # SQLAlchemy ORM models
│   │   ├── schemas/schemas.py  # Pydantic schemas
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── neonize_service.py   # WhatsApp via Neonize
│   │   │   ├── gemini_service.py    # Google Gemini AI
│   │   │   ├── message_service.py   # Message pipeline
│   │   │   └── api_key_service.py
│   │   ├── database/database.py
│   │   └── websocket/manager.py    # WS connection manager
│   └── workers/
│       └── whatsapp_worker.py  # Persistent WA worker
│
├── nginx/nginx.conf            # Reverse proxy
├── docker-compose.yml
└── .env.example
```

---

## Troubleshooting

### QR code not appearing
- Check that the `whatsapp-worker` container is running: `docker compose logs whatsapp-worker`
- Check backend logs: `docker compose logs backend`
- Make sure the `sessions` volume is writable

### WhatsApp disconnects frequently
- This is normal — WhatsApp may disconnect due to inactivity or phone going offline
- The worker auto-reconnects after 30 seconds
- Check: `docker compose logs whatsapp-worker -f`

### Gemini not responding
- Verify your `GEMINI_API_KEY` is set correctly
- Check the model name: `GEMINI_MODEL=gemini-1.5-flash`
- Check backend logs for API errors

### Database connection errors
- Ensure PostgreSQL is healthy: `docker compose ps`
- Check: `docker compose logs postgres`

### WebSocket not connecting
- Ensure the JWT token is valid (not expired)
- Check CORS_ORIGINS includes your frontend URL
- Check Nginx is proxying `/ws/` correctly

---

## Production Deployment

1. **Use a real domain** and configure SSL via Let's Encrypt
2. **Set strong secrets** — regenerate `JWT_SECRET` and `SESSION_ENCRYPTION_KEY`
3. **Use managed databases** — RDS/Cloud SQL for PostgreSQL, ElastiCache for Redis
4. **Persistent volumes** — ensure `whatsapp_sessions` volume is backed up
5. **Set `CORS_ORIGINS`** to your production domain only
6. **Monitor** with structured logging and health check endpoints

```bash
# Generate strong secrets
openssl rand -hex 64   # JWT_SECRET
openssl rand -hex 32   # SESSION_ENCRYPTION_KEY
```

---

## Known Limitations

- **One session per account** — each WhatsApp number needs its own session
- **Text messages only** — media (images, audio, video) are received but not AI-processed
- **Group replies off by default** — can be enabled in Settings
- **Neonize compatibility** — QR and connection flow depends on the installed Neonize version; check `backend/app/services/neonize_service.py` if API changes
- **Rate limits** — Google Gemini free tier has per-minute rate limits; upgrade to paid tier for production use

---

## License

MIT
