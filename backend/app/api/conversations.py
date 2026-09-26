import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database.database import get_db
from app.models.models import (
    WhatsAppAccount, Conversation, Contact, Message, User,
    MessageDirection
)
from app.schemas.schemas import (
    ConversationResponse, ConversationUpdate, MessageResponse, ContactResponse, ConversationListItem
)
from sqlalchemy import func
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


@router.get("", response_model=List[ConversationListItem])
async def list_conversations(
    account_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Get all accounts for this user
    user_accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.user_id == current_user.id
    ).all()
    account_ids = [a.id for a in user_accounts]

    if not account_ids:
        return []

    query = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.whatsapp_account_id.in_(account_ids))
    )

    if account_id:
        if account_id not in account_ids:
            raise HTTPException(status_code=403, detail="Access denied")
        query = query.filter(Conversation.whatsapp_account_id == account_id)

    conversations = query.order_by(Conversation.last_message_at.desc().nullslast()).all()
    if not conversations:
        return []

    # Batch-fetch latest message for all conversations to eliminate N+1 queries
    conv_ids = [c.id for c in conversations]
    last_messages_map = {}
    subq = (
        db.query(
            Message.conversation_id,
            func.max(Message.created_at).label("max_created")
        )
        .filter(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
        .subquery()
    )
    latest_msgs = (
        db.query(Message)
        .join(
            subq,
            (Message.conversation_id == subq.c.conversation_id)
            & (Message.created_at == subq.c.max_created)
        )
        .all()
    )
    for msg in latest_msgs:
        last_messages_map[msg.conversation_id] = msg

    result = []
    for conv in conversations:
        last_msg = last_messages_map.get(conv.id)
        result.append({
            "id": conv.id,
            "whatsapp_account_id": conv.whatsapp_account_id,
            "contact_id": conv.contact_id,
            "ai_enabled": conv.ai_enabled,
            "human_takeover": conv.human_takeover,
            "last_message_at": conv.last_message_at,
            "created_at": conv.created_at,
            "contact": {
                "id": conv.contact.id,
                "whatsapp_account_id": conv.contact.whatsapp_account_id,
                "name": conv.contact.name,
                "phone_number": conv.contact.phone_number,
                "ai_enabled": conv.contact.ai_enabled,
                "blocked": conv.contact.blocked,
                "created_at": conv.contact.created_at,
            } if conv.contact else None,
            "last_message": last_msg.content if last_msg else None,
            "last_message_direction": last_msg.direction if last_msg else None,
            "unread_count": 0,
        })

    return result


@router.get("/{conversation_id}", response_model=dict)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == conv.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "id": conv.id,
        "whatsapp_account_id": conv.whatsapp_account_id,
        "contact_id": conv.contact_id,
        "ai_enabled": conv.ai_enabled,
        "human_takeover": conv.human_takeover,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "created_at": conv.created_at.isoformat(),
        "contact": {
            "id": conv.contact.id,
            "name": conv.contact.name,
            "phone_number": conv.contact.phone_number,
            "ai_enabled": conv.contact.ai_enabled,
            "blocked": conv.contact.blocked,
        } if conv.contact else None,
    }


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == conv.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [MessageResponse.model_validate(m) for m in messages]


@router.patch("/{conversation_id}", response_model=dict)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == conv.whatsapp_account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=403, detail="Access denied")

    if data.ai_enabled is not None:
        conv.ai_enabled = data.ai_enabled
    if data.human_takeover is not None:
        conv.human_takeover = data.human_takeover

    db.commit()
    return {"id": conv.id, "ai_enabled": conv.ai_enabled, "human_takeover": conv.human_takeover}
