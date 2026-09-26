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

            # Backup session SQLite database file to PostgreSQL
            session_path = get_session_path(account_id)
            session_db = session_path + ".db"
            if os.path.exists(session_db):
                try:
                    with open(session_db, "rb") as f:
                        account.session_data = f.read()
                    logger.info(f"Backed up WhatsApp session to PostgreSQL for account {account_id} ({len(account.session_data)} bytes)")
                except Exception as bkp_err:
                    logger.warning(f"Could not backup session DB: {bkp_err}")

            db.commit()
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
    """Handle WhatsApp disconnection."""
    from app.database.database import SessionLocal
    db = SessionLocal()
    try:
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if account:
            account.status = AccountStatus.disconnected
            db.commit()
            await ws_manager.send_to_user(
                account.user_id,
                "account_disconnected",
                {"account_id": account_id, "status": "disconnected"}
            )
    except Exception as e:
        logger.error(f"Disconnected handler error: {e}")
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
                logger.error(f"Failed to send AI reply: {e}")


async def start_whatsapp_session(account_id: str):
    """Start a WhatsApp session in background."""
    session_path = get_session_path(account_id)
    session_db = session_path + ".db"

    # Restore session database from PostgreSQL if not present on disk
    if not os.path.exists(session_db):
        from app.database.database import SessionLocal
        db = SessionLocal()
        try:
            account = db.query(WhatsAppAccount).filter(WhatsAppAccount.id == account_id).first()
            if account and account.session_data:
                os.makedirs(os.path.dirname(session_db), exist_ok=True)
                with open(session_db, "wb") as f:
                    f.write(account.session_data)
                logger.info(f"Restored WhatsApp session database from PostgreSQL for account {account_id} ({len(account.session_data)} bytes)")
        except Exception as rst_err:
            logger.error(f"Failed to restore session DB: {rst_err}")
        finally:
            db.close()

    neonize_manager.register_callbacks(
        account_id=account_id,
        on_qr=handle_qr,
        on_connected=handle_connected,
        on_disconnected=handle_disconnected,
        on_message=handle_message,
    )

    try:
        await neonize_manager.start_session(account_id, session_path)
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

    # Start WhatsApp session in background
    background_tasks.add_task(start_whatsapp_session, account.id)

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
        if a.status == AccountStatus.connected and not neonize_manager.is_connected(a.id):
            a.status = AccountStatus.disconnected
            db.commit()
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
    if account.status == AccountStatus.connected and not neonize_manager.is_connected(account.id):
        account.status = AccountStatus.disconnected
        db.commit()
    return WhatsAppAccountResponse.model_validate(account)


@router.get("/accounts/{account_id}/qr", response_model=QRResponse)
async def get_qr(
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

    return QRResponse(
        qr_code=account.qr_code,
        status=account.status
    )


@router.post("/accounts/{account_id}/reconnect", response_model=WhatsAppAccountResponse)
async def reconnect_account(
    account_id: str,
    background_tasks: BackgroundTasks,
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

    account.status = AccountStatus.connecting
    account.qr_code = None
    db.commit()
    db.refresh(account)

    background_tasks.add_task(start_whatsapp_session, account.id)
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
