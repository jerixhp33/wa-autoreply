"""
WhatsApp Worker

This is a persistent background process that:
- Loads all WhatsApp accounts from DB on startup
- Reconnects sessions for accounts that were previously connected
- Registers callbacks for QR, connect, disconnect, and messages
- Processes incoming messages and generates AI replies
- Runs indefinitely, restarted by Docker
- Robust reconnection engine with exponential backoff & circuit breaker

Run with: python -m workers.whatsapp_worker
"""
import asyncio
import logging
import os
import sys
import time
from typing import Dict

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


# ── Reconnection Engine ──────────────────────────────────────────────────────
# Exponential backoff delays: 10s → 30s → 1m → 2m → 5m → 10m (max)
RECONNECT_DELAYS = [10, 30, 60, 120, 300, 600]
MAX_RECONNECT_ATTEMPTS = 10

# Per-account reconnect tracking: {account_id: {"attempts": int, "last_attempt": float}}
_reconnect_state: Dict[str, dict] = {}
# Accounts that should NOT be auto-reconnected (manually disconnected/deleted)
_reconnect_cancelled: set = set()


def _get_reconnect_delay(attempts: int) -> int:
    """Get backoff delay for the given attempt number."""
    idx = min(attempts, len(RECONNECT_DELAYS) - 1)
    return RECONNECT_DELAYS[idx]


def _reset_reconnect(account_id: str):
    """Reset reconnect counter for an account (called on successful connection)."""
    _reconnect_state.pop(account_id, None)
    _reconnect_cancelled.discard(account_id)
    logger.info(f"🔄 Reconnect state reset for {account_id}")


def _cancel_reconnect(account_id: str):
    """Cancel any pending reconnect for an account."""
    _reconnect_cancelled.add(account_id)
    _reconnect_state.pop(account_id, None)


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
    """Handle successful connection — reset reconnect counter."""
    # Reset reconnect state on successful connection
    _reset_reconnect(account_id)

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
            logger.info(f"✅ Account {account_id} connected! Phone: {phone_number}")
    except Exception as e:
        logger.error(f"Connected handler error: {e}")
    finally:
        db.close()


async def on_disconnected(account_id: str):
    """Handle disconnection with exponential backoff reconnection engine."""
    # Check if reconnect was cancelled (manual disconnect/delete)
    if account_id in _reconnect_cancelled:
        logger.info(f"Reconnect cancelled for {account_id}, not retrying")
        return

    # Update DB status
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.status = AccountStatus.disconnected
            db.commit()
            logger.warning(f"⚠️ Account {account_id} disconnected")
    except Exception as e:
        logger.error(f"Disconnect handler error: {e}")
    finally:
        db.close()

    # Get or init reconnect state for this account
    state = _reconnect_state.get(account_id, {"attempts": 0, "last_attempt": 0})
    attempts = state["attempts"]

    # Circuit breaker: max attempts reached → mark as error, stop retrying
    if attempts >= MAX_RECONNECT_ATTEMPTS:
        logger.error(
            f"🔴 CIRCUIT BREAKER: Account {account_id} failed {attempts} consecutive "
            f"reconnects. Marking as ERROR. Manual intervention required."
        )
        db = SessionLocal()
        try:
            account = db.query(WhatsAppAccount).filter(
                WhatsAppAccount.id == account_id
            ).first()
            if account:
                account.status = AccountStatus.error
                db.commit()
        except Exception as e:
            logger.error(f"Circuit breaker DB update error: {e}")
        finally:
            db.close()
        _reconnect_state.pop(account_id, None)
        return

    # Calculate backoff delay
    delay = _get_reconnect_delay(attempts)
    attempts += 1
    _reconnect_state[account_id] = {"attempts": attempts, "last_attempt": time.time()}

    logger.info(
        f"🔄 Reconnect attempt {attempts}/{MAX_RECONNECT_ATTEMPTS} for {account_id} "
        f"in {delay}s (backoff)"
    )

    # Wait with backoff
    await asyncio.sleep(delay)

    # Double-check cancellation after sleep
    if account_id in _reconnect_cancelled:
        logger.info(f"Reconnect cancelled for {account_id} during backoff wait")
        return

    # Attempt reconnect
    logger.info(f"🔄 Attempting reconnect for {account_id} (attempt {attempts})...")
    try:
        await start_account_session(account_id)
    except Exception as e:
        logger.error(f"Reconnect attempt {attempts} failed for {account_id}: {e}")


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
        sticker_path = res.get("sticker_path") if isinstance(res, dict) else None

        if sticker_path:
            try:
                await neonize_manager.send_sticker(account_id, sender, sticker_path)
                logger.info(f"AI sticker sent to {sender}")
            except Exception as e:
                logger.error(f"Failed to send sticker to {sender}: {e}")
        elif audio_path:
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


async def health_heartbeat():
    """
    Periodic health check every 60s:
    - Log active/total sessions
    - Detect zombie sessions (thread dead but marked connected)
    - Auto-trigger reconnect for zombies
    """
    while True:
        await asyncio.sleep(60)
        try:
            active = 0
            total = len(neonize_manager.sessions)
            zombies = []

            for acct_id, session in list(neonize_manager.sessions.items()):
                if session.connected:
                    # Verify thread is actually alive
                    if session._thread and session._thread.is_alive():
                        active += 1
                    else:
                        # Zombie: marked connected but thread is dead
                        zombies.append(acct_id)
                        session.connected = False
                        logger.warning(
                            f"🧟 Zombie session detected: {acct_id} "
                            f"(marked connected but thread dead)"
                        )

            # Log reconnect state summary
            pending_reconnects = len(_reconnect_state)
            logger.info(
                f"💓 Heartbeat: {active}/{total} sessions connected"
                + (f", {pending_reconnects} pending reconnects" if pending_reconnects else "")
                + (f", {len(zombies)} zombies detected" if zombies else "")
            )

            # Trigger reconnect for zombies
            for acct_id in zombies:
                if acct_id not in _reconnect_cancelled:
                    logger.info(f"🔄 Auto-reconnecting zombie session {acct_id}")
                    asyncio.create_task(on_disconnected(acct_id))

            # Sync DB status for truly connected sessions
            if active > 0:
                db = SessionLocal()
                try:
                    for acct_id, session in neonize_manager.sessions.items():
                        if session.connected and session._thread and session._thread.is_alive():
                            account = db.query(WhatsAppAccount).filter(
                                WhatsAppAccount.id == acct_id
                            ).first()
                            if account and account.status != AccountStatus.connected:
                                account.status = AccountStatus.connected
                                db.commit()
                                logger.info(f"Synced DB status to connected for {acct_id}")
                finally:
                    db.close()

        except Exception as e:
            logger.error(f"Health heartbeat error: {e}")


async def main():
    """Main worker loop."""
    logger.info("🚀 WhatsApp Worker starting...")

    create_tables()
    logger.info("Database ready")

    await load_and_start_sessions()

    # Start health heartbeat in background
    asyncio.create_task(health_heartbeat())

    logger.info("✅ Worker ready — monitoring sessions with reconnection engine...")

    # Keep alive loop
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by keyboard interrupt")
