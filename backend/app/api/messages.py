import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import WhatsAppAccount, Conversation, Contact, Message, User, MessageDirection, MessageStatus
from app.schemas.schemas import SendMessageRequest
from app.services.auth_service import get_current_user
from app.services.neonize_service import neonize_manager
from app.services.message_service import get_or_create_contact, get_or_create_conversation, save_message
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/api/messages", tags=["messages"])
logger = logging.getLogger(__name__)


@router.post("/send")
async def send_message(
    data: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verify account ownership
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == data.account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not neonize_manager.is_connected(data.account_id):
        raise HTTPException(status_code=400, detail="WhatsApp account is not connected")

    # Normalize phone number
    phone = data.phone.strip().replace("+", "").replace(" ", "")

    # Get or create contact + conversation
    contact = get_or_create_contact(db, data.account_id, phone)
    conv = get_or_create_conversation(db, data.account_id, contact.id)

    # Send via WhatsApp
    try:
        await neonize_manager.send_message(data.account_id, phone, data.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")

    # Save to DB
    saved = save_message(
        db=db,
        conversation_id=conv.id,
        content=data.message,
        direction=MessageDirection.outgoing,
        ai_generated=False,
        status=MessageStatus.sent,
    )

    # Emit WS event
    await ws_manager.send_to_user(
        current_user.id,
        "message_sent",
        {
            "id": saved.id,
            "conversation_id": conv.id,
            "account_id": data.account_id,
            "content": data.message,
            "direction": "outgoing",
            "ai_generated": False,
            "created_at": saved.created_at.isoformat(),
        }
    )

    return {
        "id": saved.id,
        "conversation_id": conv.id,
        "status": "sent",
        "message": data.message
    }
