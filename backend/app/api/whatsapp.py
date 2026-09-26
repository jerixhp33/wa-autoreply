import os
import asyncio
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import WhatsAppAccount, BotSettings, AccountStatus, User
from app.schemas.schemas import (
    WhatsAppAccountCreate, WhatsAppAccountResponse, QRResponse
)
from app.services.auth_service import get_current_user
from app.services.neonize_service import neonize_manager
from app.services.message_service import process_incoming_message
from app.websocket.manager import ws_manager
from app.config import settings

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])
logger = logging.getLogger(__name__)


def get_session_path(account_id: str) -> str:
    """
    Returns the session name/path for Neonize.
    Neonize appends .db internally, so we pass the path WITHOUT .db.
    """
    sessions_dir = settings.sessions_dir
    os.makedirs(sessions_dir, exist_ok=True)
    return os.path.join(sessions_dir, account_id)


async def handle_qr(account_id: str, qr_data: str):
    """Handle QR code update - save to DB and emit WS event."""
    from app.database.database import SessionLocal
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.qr_code = qr_data
            account.status = AccountStatus.connecting
            db.commit()
            await ws_manager.send_to_user(
                account.user_id,
                "qr_updated",
                {"account_id": account_id, "qr_code": qr_data, "status": "waiting_scan"}
            )
    except Exception as e:
        logger.error(f"QR handler error: {e}")
    finally:
        db.close()


def backup_session_to_db(account_id: str, db: Session):
    """
    Checkpoints SQLite WAL and backs up the entire session database
    to PostgreSQL for persistent durability across Render redeploys and restarts.
    """
    session_path = get_session_path(account_id)
    session_db = session_path + ".db"
    candidates = [
        session_db,
        session_path,
        session_path + ".sqlite3",
        session_path + ".sqlite",
    ]
    target_file = None
    for cand in candidates:
        if os.path.exists(cand) and os.path.isfile(cand) and os.path.getsize(cand) > 0:
            target_file = cand
            break

    if not target_file:
        return

    # Checkpoint SQLite WAL to flush all active transactions and keys into the primary DB file
    try:
        import sqlite3
        conn = sqlite3.connect(target_file, timeout=5.0)
        conn.execute("PRAGMA wal_checkpoint(FULL);")
        conn.commit()
        conn.close()
    except Exception as wal_err:
        logger.debug(f"WAL checkpoint note for {account_id}: {wal_err}")

    try:
        with open(target_file, "rb") as f:
            data = f.read()
        if data and len(data) > 0:
            account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
            if account:
                account.session_data = data
                db.commit()
                logger.info(f"Backed up session DB to PostgreSQL for account {account_id} ({len(data)} bytes)")
    except Exception as e:
        logger.warning(f"Could not backup session DB for {account_id}: {e}")


async def handle_connected(account_id: str, phone_number: str):
    """Handle successful WhatsApp connection."""
    from app.database.database import SessionLocal
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

            # Immediate WAL checkpoint and persistent backup to PostgreSQL
            backup_session_to_db(account_id, db)

            await ws_manager.send_to_user(
                account.user_id,
                "account_connected",
                {
                    "account_id": account_id,
                    "phone_number": phone_number,
                    "status": "connected"
                }
            )
    except Exception as e:
        logger.error(f"Connected handler error: {e}")
    finally:
        db.close()


async def handle_disconnected(account_id: str):
    """Handle temporary socket disconnect without erasing session credentials."""
    logger.warning(f"Account {account_id} socket disconnected; waiting for reconnect...")
    # NOTE: Do NOT erase session_data or mark permanently disconnected in DB!
    # whatsmeow will automatically re-establish the socket connection.


async def handle_logged_out(account_id: str):
    """Handle permanent WhatsApp logout (device unlinked on phone)."""
    from app.database.database import SessionLocal
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.status = AccountStatus.disconnected
            account.session_data = None
            account.qr_code = None
            db.commit()

            # Clean disk files
            session_path = get_session_path(account_id)
            for fpath in [session_path + ".db", session_path, session_path + ".db-wal", session_path + ".db-shm"]:
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

            await ws_manager.send_to_user(
                account.user_id,
                "account_disconnected",
                {"account_id": account_id, "status": "disconnected"}
            )
    except Exception as e:
        logger.error(f"Logged out handler error: {e}")
    finally:
        db.close()


# Track recently processed message IDs to prevent duplicates (FIFO via OrderedDict)
from collections import OrderedDict
_processed_message_ids: OrderedDict = OrderedDict()
_MAX_PROCESSED_IDS = 500


async def handle_message(
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
    """Handle incoming WhatsApp message."""
    global _processed_message_ids

    # Deduplicate — WhatsApp can deliver the same message event twice
    if message_id:
        if message_id in _processed_message_ids:
            logger.debug(f"Skipping duplicate message: {message_id}")
            return
        _processed_message_ids[message_id] = True
        # Prune oldest items deterministically
        while len(_processed_message_ids) > _MAX_PROCESSED_IDS:
            _processed_message_ids.popitem(last=False)

    async def ws_callback(event: str, data: dict, user_id: str):
        await ws_manager.send_to_user(user_id, event, data)

    res = await process_incoming_message(
        account_id=account_id,
        sender=sender,
        content=content,
        is_group=is_group,
        message_id=message_id,
        ws_callback=ws_callback,
        media_path=media_path,
        media_type=media_type,
        mime_type=mime_type,
        caption=caption,
    )

    if res:
        reply_text = res.get("reply") if isinstance(res, dict) else res
        audio_path = res.get("audio_path") if isinstance(res, dict) else None
        sticker_path = res.get("sticker_path") if isinstance(res, dict) else None
        conversation_id = res.get("conversation_id") if isinstance(res, dict) else None
        msg_id = res.get("message_id") if isinstance(res, dict) else None

        from app.services.message_service import update_outgoing_message_status

        if sticker_path:
            sent_sticker = False
            try:
                await neonize_manager.send_sticker(account_id, sender, sticker_path)
                logger.info(f"AI sticker sent to {sender}")
                sent_sticker = True
            except Exception as e:
                logger.error(f"Failed to send AI sticker to {sender}: {e}")

            if conversation_id:
                await update_outgoing_message_status(
                    account_id=account_id,
                    conversation_id=conversation_id,
                    message_content="[Sticker]",
                    success=sent_sticker,
                    message_id=msg_id,
                )
        elif audio_path:
            sent_audio = False
            try:
                await neonize_manager.send_audio(account_id, sender, audio_path, is_ptt=True)
                logger.info(f"AI voice note sent to {sender}")
                sent_audio = True
            except Exception as e:
                logger.warning(f"Failed to send voice note, falling back to text: {e}")
                if reply_text:
                    try:
                        await neonize_manager.send_message(account_id, sender, reply_text)
                        sent_audio = True
                        logger.info(f"AI text fallback sent to {sender}")
                    except Exception as send_err:
                        logger.error(f"Failed to send text fallback: {send_err}")

            if conversation_id:
                await update_outgoing_message_status(
                    account_id=account_id,
                    conversation_id=conversation_id,
                    message_content=reply_text,
                    success=sent_audio,
                    message_id=msg_id,
                )
        elif reply_text:
            sent_text = False
            try:
                await neonize_manager.send_message(account_id, sender, reply_text)
                logger.info(f"AI reply sent to {sender}")
                sent_text = True
            except Exception as e:
                logger.error(f"Failed to send AI reply: {e}")

            if conversation_id:
                await update_outgoing_message_status(
                    account_id=account_id,
                    conversation_id=conversation_id,
                    message_content=reply_text,
                    success=sent_text,
                    message_id=msg_id,
                )


_pending_starts: set = set()


async def safe_start_whatsapp_session(account_id: str, force_new_qr: bool = False):
    """Start WhatsApp session with in-flight deduplication to prevent duplicate tasks."""
    if account_id in _pending_starts:
        logger.info(f"Session start already in progress for account {account_id}, ignoring duplicate request")
        return
    _pending_starts.add(account_id)
    try:
        await start_whatsapp_session(account_id, force_new_qr=force_new_qr)
    finally:
        _pending_starts.discard(account_id)


async def start_whatsapp_session(account_id: str, force_new_qr: bool = False):
    """Start a WhatsApp session in background, restoring persistent DB if missing or resetting for fresh QR."""
    session_path = get_session_path(account_id)
    session_db = session_path + ".db"

    phone_from_db = None
    from app.database.database import SessionLocal
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
        if account:
            if force_new_qr:
                # User explicitly requested a fresh QR scan: clear stored credentials
                logger.info(f"Clearing old session credentials for account {account_id} for fresh QR code")
                account.session_data = None
                account.phone_number = None
                account.qr_code = None
                account.status = AccountStatus.connecting
                db.commit()
                for fpath in [session_db, session_path, session_db + "-wal", session_db + "-shm", session_path + "-wal", session_path + "-shm"]:
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
            else:
                phone_from_db = account.phone_number
                has_disk_file = (
                    (os.path.exists(session_db) and os.path.getsize(session_db) > 0) or
                    (os.path.exists(session_path) and os.path.getsize(session_path) > 0)
                )
                if not has_disk_file and account.session_data and len(account.session_data) > 0:
                    os.makedirs(os.path.dirname(session_db), exist_ok=True)
                    with open(session_db, "wb") as f:
                        f.write(account.session_data)
                    with open(session_path, "wb") as f:
                        f.write(account.session_data)
                    logger.info(f"Restored WhatsApp session database from PostgreSQL for account {account_id} ({len(account.session_data)} bytes)")
    except Exception as rst_err:
        logger.error(f"Failed in start_whatsapp_session DB setup: {rst_err}")
    finally:
        db.close()

    neonize_manager.register_callbacks(
        account_id=account_id,
        on_qr=handle_qr,
        on_connected=handle_connected,
        on_disconnected=handle_disconnected,
        on_message=handle_message,
        on_logged_out=handle_logged_out,
    )

    try:
        await neonize_manager.start_session(account_id, session_path, phone_number=phone_from_db)
    except Exception as e:
        logger.error(f"Failed to start session {account_id}: {e}")
        from app.database.database import SessionLocal
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


@router.post("/accounts", response_model=WhatsAppAccountResponse, status_code=201)
async def create_account(
    data: WhatsAppAccountCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = WhatsAppAccount(
        user_id=current_user.id,
        name=data.name,
        status=AccountStatus.connecting,
        session_path=None,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    # Create default bot settings
    bot_settings = BotSettings(whatsapp_account_id=account.id)
    db.add(bot_settings)
    db.commit()

    # Set session path now we have ID
    account.session_path = get_session_path(account.id)
    db.commit()
    db.refresh(account)

    # Start WhatsApp session in background safely
    background_tasks.add_task(safe_start_whatsapp_session, account.id)

    return WhatsAppAccountResponse.model_validate(account)


@router.get("/accounts", response_model=List[WhatsAppAccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = (
        db.query(WhatsAppAccount)
        .filter(WhatsAppAccount.user_id == current_user.id)
        .order_by(WhatsAppAccount.created_at.desc())
        .all()
    )
    for a in accounts:
        is_conn = neonize_manager.is_connected(a.id)
        if is_conn:
            if a.status != AccountStatus.connected:
                a.status = AccountStatus.connected
                session = neonize_manager.get_session(a.id)
                if session and session.phone_number:
                    a.phone_number = session.phone_number
                db.commit()
        else:
            # DO NOT overwrite a.status to disconnected in a GET endpoint!
            # If account was connected and has session credentials, resume it in the background
            if a.status == AccountStatus.connected and a.id not in neonize_manager.sessions and a.id not in _pending_starts:
                logger.info(f"Auto-triggering resume for active account {a.id}")
                asyncio.create_task(safe_start_whatsapp_session(a.id))
    return [WhatsAppAccountResponse.model_validate(a) for a in accounts]


@router.get("/accounts/{account_id}", response_model=WhatsAppAccountResponse)
async def get_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_conn = neonize_manager.is_connected(account.id)
    if is_conn:
        if account.status != AccountStatus.connected:
            account.status = AccountStatus.connected
            session = neonize_manager.get_session(account.id)
            if session and session.phone_number:
                account.phone_number = session.phone_number
            db.commit()
    elif account.status == AccountStatus.connected and account.id not in neonize_manager.sessions and account.id not in _pending_starts:
        logger.info(f"Auto-triggering resume for active account {account.id}")
        asyncio.create_task(safe_start_whatsapp_session(account.id))

    return WhatsAppAccountResponse.model_validate(account)


@router.get("/accounts/{account_id}/qr", response_model=QRResponse)
async def get_qr(
    account_id: str,
    background_tasks: BackgroundTasks,
    force_new_qr: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_conn = neonize_manager.is_connected(account.id)
    if is_conn and not force_new_qr:
        if account.status != AccountStatus.connected:
            account.status = AccountStatus.connected
            account.qr_code = None
            db.commit()
        return QRResponse(qr_code=None, status="connected")

    if force_new_qr:
        logger.info(f"Force fresh QR requested for account {account_id}")
        await neonize_manager.stop_session(account_id)
        await asyncio.sleep(1.0)
        background_tasks.add_task(safe_start_whatsapp_session, account.id, True)
    elif account_id not in neonize_manager.sessions and account_id not in _pending_starts:
        logger.info(f"Auto-starting session for account {account_id} on get_qr poll")
        account.status = AccountStatus.connecting
        db.commit()
        background_tasks.add_task(safe_start_whatsapp_session, account.id, False)

    return QRResponse(
        qr_code=account.qr_code if not is_conn else None,
        status=account.status
    )


@router.post("/accounts/{account_id}/reconnect", response_model=WhatsAppAccountResponse)
async def reconnect_account(
    account_id: str,
    background_tasks: BackgroundTasks,
    force_new_qr: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not force_new_qr and neonize_manager.is_connected(account_id):
        return WhatsAppAccountResponse.model_validate(account)

    await neonize_manager.stop_session(account_id)
    await asyncio.sleep(1.0)  # Ensure SQLite file lock release

    account.status = AccountStatus.connecting
    account.qr_code = None
    if force_new_qr:
        account.session_data = None
        account.phone_number = None
    db.commit()
    db.refresh(account)

    background_tasks.add_task(safe_start_whatsapp_session, account.id, force_new_qr)
    return WhatsAppAccountResponse.model_validate(account)


@router.post("/accounts/{account_id}/disconnect")
async def disconnect_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    await neonize_manager.stop_session(account_id)
    account.status = AccountStatus.disconnected
    db.commit()

    return {"message": "Account disconnected successfully"}


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Stop session if active
    await neonize_manager.stop_session(account_id)

    # Remove session file (neonize adds .db suffix)
    session_name = get_session_path(account_id)
    session_db = session_name + ".db"
    if os.path.exists(session_db):
        os.remove(session_db)
    if os.path.exists(session_name):
        os.remove(session_name)

    db.delete(account)
    db.commit()
    return {"message": "Account deleted"}
