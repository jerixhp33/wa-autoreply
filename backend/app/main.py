import asyncio
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database.database import create_tables
from app.websocket.manager import ws_manager
from app.services.auth_service import decode_token, get_user_by_id
from app.database.database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def auto_reconnect_sessions():
    """
    On server boot, check for accounts that were previously connected
    and attempt to resume their WhatsApp sessions if session files exist,
    or mark them as disconnected so the dashboard accurately reflects status.
    """
    await asyncio.sleep(2)
    from app.database.database import SessionLocal
    from app.models.models import WhatsAppAccount, AccountStatus
    from app.api.whatsapp import start_whatsapp_session, get_session_path

    db = SessionLocal()
    try:
        accounts = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.status.in_([AccountStatus.connected, AccountStatus.connecting])
        ).all()
        for account in accounts:
            session_path = get_session_path(account.id)
            session_db = session_path + ".db"

            # Restore from PostgreSQL if missing on disk
            if not os.path.exists(session_db) and getattr(account, "session_data", None):
                try:
                    os.makedirs(os.path.dirname(session_db), exist_ok=True)
                    with open(session_db, "wb") as f:
                        f.write(account.session_data)
                    logger.info(f"Restored session database from PostgreSQL for account {account.id}")
                except Exception as rst_err:
                    logger.warning(f"Could not restore session DB: {rst_err}")

            if os.path.exists(session_db):
                logger.info(f"Auto-resuming session for account {account.id} ({account.name})...")
                asyncio.create_task(start_whatsapp_session(account.id))
            else:
                logger.info(f"No existing session database for account {account.id}, marking disconnected")
                account.status = AccountStatus.disconnected
                db.commit()
    except Exception as e:
        logger.error(f"Error during auto-reconnect: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting WhatsApp AI Backend...")
    create_tables()
    logger.info("Database tables created/verified")
    asyncio.create_task(auto_reconnect_sessions())
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="WhatsApp AI Auto Reply API",
    description="Backend API for WhatsApp AI Auto Reply application",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Rate Limiting
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount media directory for serving downloaded media files
import os
from fastapi.staticfiles import StaticFiles
_media_dir = settings.media_dir
os.makedirs(_media_dir, exist_ok=True)
try:
    app.mount("/media", StaticFiles(directory=_media_dir), name="media")
except Exception:
    pass  # Media dir will be created at runtime

# Import and include routers
from app.api.auth import router as auth_router
from app.api.whatsapp import router as whatsapp_router
from app.api.conversations import router as conversations_router
from app.api.messages import router as messages_router
from app.api.bot import router as bot_router
from app.api.api_keys import router as api_keys_router
from app.api.dashboard import router as dashboard_router
from app.api.public import router as public_router
from app.api.documents import router as documents_router

app.include_router(auth_router)
app.include_router(whatsapp_router)
app.include_router(conversations_router)
app.include_router(messages_router)
app.include_router(bot_router)
app.include_router(api_keys_router)
app.include_router(dashboard_router)
app.include_router(public_router)
app.include_router(documents_router)


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001)
        return

    db = SessionLocal()
    try:
        user = get_user_by_id(db, user_id)
        if not user:
            await websocket.close(code=4001)
            return
    finally:
        db.close()

    await ws_manager.connect(websocket, user_id)
    logger.info(f"WebSocket connected: user={user_id}")

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket, user_id)


@app.get("/")
async def root():
    return {"message": "WhatsApp AI Backend", "version": "1.0.0"}


@app.get("/api/health")
async def health():
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}