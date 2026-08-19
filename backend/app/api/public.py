import logging
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database.database import get_db
from app.models.models import WhatsAppAccount, MessageDirection, MessageStatus, User
from app.schemas.schemas import PublicSendMessageRequest
from app.services.api_key_service import validate_api_key
from app.services.neonize_service import neonize_manager
from app.services.message_service import get_or_create_contact, get_or_create_conversation, save_message

router = APIRouter(prefix="/api/v1", tags=["public-api"])
logger = logging.getLogger(__name__)


async def get_api_key_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    raw_key = authorization.removeprefix("Bearer ").strip()
    api_key = validate_api_key(db, raw_key)
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return api_key.user


@router.post("/messages/send")
async def public_send_message(
    data: PublicSendMessageRequest,
    user: User = Depends(get_api_key_user),
    db: Session = Depends(get_db),
):
    # Verify this account belongs to the API key's user
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == data.account_id,
        WhatsAppAccount.user_id == user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not neonize_manager.is_connected(data.account_id):
        raise HTTPException(status_code=400, detail="WhatsApp account is not connected")

    phone = data.phone.strip().replace("+", "").replace(" ", "")

    try:
        await neonize_manager.send_message(data.account_id, phone, data.message)
    except Exception as e:
        logger.error(f"Public API send error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")

    contact = get_or_create_contact(db, data.account_id, phone)
    conv = get_or_create_conversation(db, data.account_id, contact.id)

    saved = save_message(
        db=db,
        conversation_id=conv.id,
        content=data.message,
        direction=MessageDirection.outgoing,
        ai_generated=False,
        status=MessageStatus.sent,
    )

    return {
        "id": saved.id,
        "conversation_id": conv.id,
        "status": "sent",
        "message": data.message
    }
