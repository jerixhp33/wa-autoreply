"""
WhatsApp Worker

This is a persistent background process that:
- Loads all WhatsApp accounts from DB on startup
- Reconnects sessions for accounts that were previously connected
- Registers callbacks for QR, connect, disconnect, and messages
- Processes incoming messages and generates AI replies
- Runs indefinitely, restarted by Docker

Run with: python -m workers.whatsapp_worker
"""
import asyncio
import logging
import os
import sys

# Add backend root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database.database import SessionLocal, create_tables
from app.models.models import WhatsAppAccount, AccountStatus
from app.services.neonize_service import neonize_manager
from app.services.message_service import process_incoming_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("whatsapp_worker")


def get_session_name(account_id: str) -> str:
    """
    Neonize uses `name` as the session file identifier.
    The session DB will be at: <name>.db in the current dir,
    or we can include the full path in the name.
    """
    sessions_dir = settings.sessions_dir
    os.makedirs(sessions_dir, exist_ok=True)
    # Neonize appends .db automatically, so pass the path without extension
    return os.path.join(sessions_dir, account_id)


async def on_qr(account_id: str, qr_data: str):
    """Handle QR code update."""
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.qr_code = qr_data
            account.status = AccountStatus.connecting
            db.commit()
            logger.info(f"QR updated for account {account_id}")
    except Exception as e:
        logger.error(f"QR handler error: {e}")
    finally:
        db.close()


async def on_connected(account_id: str, phone_number: str):
    """Handle successful connection."""
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.status = AccountStatus.connected
            account.qr_code = None
            if phone_number:
                account.phone_number = phone_number
            db.commit()
            logger.info(f"Account {account_id} connected! Phone: {phone_number}")
    except Exception as e:
        logger.error(f"Connected handler error: {e}")
    finally:
        db.close()


async def on_disconnected(account_id: str):
    """Handle disconnection — attempt reconnect after delay."""
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.status = AccountStatus.disconnected
            db.commit()
            logger.warning(f"Account {account_id} disconnected")
    except Exception as e:
        logger.error(f"Disconnect handler error: {e}")
    finally:
        db.close()

    # Schedule reconnect after 30s
    await asyncio.sleep(30)
    logger.info(f"Attempting reconnect for account {account_id}...")
    await start_account_session(account_id)


async def on_message(
    account_id: str,
    sender: str,
    content: str,
    is_group: bool,
    message_id: str = None,
    media_path: str = None,
    media_type: str = "text",
    mime_type: str = None,
    caption: str = None,
    **kwargs,
):
    """Handle incoming message and generate AI reply."""
    logger.info(f"Message from {sender} on {account_id}: {content[:50] if content else media_type}...")

    res = await process_incoming_message(
        account_id=account_id,
        sender=sender,
        content=content,
        is_group=is_group,
        message_id=message_id,
        ws_callback=None,
        media_path=media_path,
        media_type=media_type,
        mime_type=mime_type,
        caption=caption,
    )

    if res:
        reply_text = res.get("reply") if isinstance(res, dict) else res
        audio_path = res.get("audio_path") if isinstance(res, dict) else None

        if audio_path:
            try:
                await neonize_manager.send_audio(account_id, sender, audio_path, is_ptt=True)
                logger.info(f"AI voice note sent to {sender}")
            except Exception as e:
                logger.warning(f"Failed to send voice note, falling back to text: {e}")
                if reply_text:
                    try:
                        await neonize_manager.send_message(account_id, sender, reply_text)
                    except Exception as send_err:
                        logger.error(f"Failed to send text fallback: {send_err}")
        elif reply_text:
            try:
                await neonize_manager.send_message(account_id, sender, reply_text)
                logger.info(f"AI reply sent to {sender}")
            except Exception as e:
                logger.error(f"Failed to send AI reply to {sender}: {e}")


async def start_account_session(account_id: str):
    """Register callbacks and start a WhatsApp session."""
    session_name = get_session_name(account_id)

    neonize_manager.register_callbacks(
        account_id=account_id,
        on_qr=on_qr,
        on_connected=on_connected,
        on_disconnected=on_disconnected,
        on_message=on_message,
    )

    try:
        await neonize_manager.start_session(account_id, session_name)
        logger.info(f"Session started for {account_id}")
    except Exception as e:
        logger.error(f"Failed to start session {account_id}: {e}", exc_info=True)
        db = SessionLocal()
        try:
            account = db.query(WhatsAppAccount).filter(
                WhatsAppAccount.id == account_id
            ).first()
            if account:
                account.status = AccountStatus.error
                db.commit()
        finally:
            db.close()


async def load_and_start_sessions():
    """Load all accounts from DB and (re)start their sessions."""
    db = SessionLocal()
    try:
        accounts = db.query(WhatsAppAccount).all()
        logger.info(f"Found {len(accounts)} WhatsApp accounts")

        for account in accounts:
            session_name = get_session_name(account.id)
            session_db_path = session_name + ".db"

            if os.path.exists(session_db_path):
                logger.info(f"Resuming session for {account.id} ({account.name})")
                # Run session start in background — don't await the full connect
                asyncio.create_task(start_account_session(account.id))
            else:
                if account.status == AccountStatus.connected:
                    account.status = AccountStatus.disconnected
                    db.commit()
                    logger.info(f"Marked {account.id} as disconnected (no session file)")

    except Exception as e:
        logger.error(f"Error loading accounts: {e}", exc_info=True)
    finally:
        db.close()


async def main():
    """Main worker loop."""
    logger.info("WhatsApp Worker starting...")

    create_tables()
    logger.info("Database ready")

    await load_and_start_sessions()
    logger.info("Worker ready — monitoring sessions...")

    # Keep alive loop
    while True:
        await asyncio.sleep(60)
        # Log active sessions count
        active = sum(1 for s in neonize_manager.sessions.values() if s.connected)
        total = len(neonize_manager.sessions)
        logger.info(f"Sessions: {active}/{total} connected")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by keyboard interrupt")
