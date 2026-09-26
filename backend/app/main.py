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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting WhatsApp AI Backend...")
    create_tables()
    logger.info("Database tables created/verified")
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