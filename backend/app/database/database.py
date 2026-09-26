from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import logging
from app.config import settings
from app.models.models import Base

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Create all tables in the database and auto-migrate newly added columns."""
    Base.metadata.create_all(bind=engine)

    columns = [
        ("bot_settings", "voice_reply_enabled", "BOOLEAN DEFAULT FALSE"),
        ("bot_settings", "voice_name", "VARCHAR DEFAULT 'en-IN-NeerjaNeural'"),
        ("bot_settings", "voice_reply_mode", "VARCHAR DEFAULT 'audio_only'"),
        ("bot_settings", "web_search_enabled", "BOOLEAN DEFAULT TRUE"),
        ("bot_settings", "stickers_enabled", "BOOLEAN DEFAULT TRUE"),
        ("messages", "media_path", "VARCHAR"),
        ("messages", "media_mime_type", "VARCHAR"),
        ("messages", "media_caption", "TEXT"),
        ("messages", "transcription", "TEXT"),
        ("whatsapp_accounts", "session_data", "BYTEA"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type};"))
                conn.commit()
                logger.info(f"Verified column {table}.{col}")
            except Exception as e:
                logger.debug(f"Column check for {table}.{col}: {e}")


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI routes to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
