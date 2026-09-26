from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.database import get_db
from app.models.models import WhatsAppAccount, Message, Conversation, User, AccountStatus, MessageDirection
from app.schemas.schemas import DashboardStats
from app.services.auth_service import get_current_user

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Get all accounts for this user
    accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.user_id == current_user.id
    ).all()
    account_ids = [a.id for a in accounts]

    # Connected accounts
    connected = sum(1 for a in accounts if a.status == AccountStatus.connected)

    # Today's date range
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Get conversation IDs for these accounts
    conv_ids = [
        c.id for c in db.query(Conversation.id).filter(
            Conversation.whatsapp_account_id.in_(account_ids)
        ).all()
    ]

    # Messages today
    messages_today = db.query(func.count(Message.id)).filter(
        Message.conversation_id.in_(conv_ids),
        Message.created_at >= today_start
    ).scalar() or 0

    # AI replies today
    ai_replies_today = db.query(func.count(Message.id)).filter(
        Message.conversation_id.in_(conv_ids),
        Message.ai_generated == True,
        Message.created_at >= today_start
    ).scalar() or 0

    # Active conversations (had activity in last 24 hours)
    active_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    active_conversations = db.query(func.count(Conversation.id)).filter(
        Conversation.whatsapp_account_id.in_(account_ids),
        Conversation.last_message_at >= active_cutoff
    ).scalar() or 0

    return DashboardStats(
        connected_accounts=connected,
        messages_today=messages_today,
        ai_replies_today=ai_replies_today,
        active_conversations=active_conversations,
    )
