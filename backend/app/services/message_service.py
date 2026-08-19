"""
Message Service

Handles the full message flow:
WhatsApp → Save → AI Processing → Reply
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict
from sqlalchemy.orm import Session

from app.models.models import (
    WhatsAppAccount, Contact, Conversation, Message, BotSettings,
    MessageDirection, MessageStatus, AccountStatus
)
from app.services.gemini_service import gemini_service
from app.database.database import SessionLocal

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    """Remove non-digit characters for consistent phone number storage."""
    return phone.replace('+', '').replace(' ', '').replace('-', '').strip()


def get_or_create_contact(
    db: Session,
    account_id: str,
    phone_number: str,
    name: Optional[str] = None
) -> Contact:
    """Get existing contact or create a new one."""
    phone_number = normalize_phone(phone_number)
    contact = db.query(Contact).filter(
        Contact.whatsapp_account_id == account_id,
        Contact.phone_number == phone_number
    ).first()

    if not contact:
        contact = Contact(
            whatsapp_account_id=account_id,
            phone_number=phone_number,
            name=name or phone_number,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

    return contact


def get_or_create_conversation(
    db: Session,
    account_id: str,
    contact_id: str
) -> Conversation:
    """Get existing conversation or create a new one."""
    conv = db.query(Conversation).filter(
        Conversation.whatsapp_account_id == account_id,
        Conversation.contact_id == contact_id
    ).first()

    if not conv:
        conv = Conversation(
            whatsapp_account_id=account_id,
            contact_id=contact_id,
            ai_enabled=True,
            human_takeover=False,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    return conv


def save_message(
    db: Session,
    conversation_id: str,
    content: str,
    direction: str,
    ai_generated: bool = False,
    status: str = MessageStatus.sent,
    whatsapp_message_id: Optional[str] = None,
    message_type: str = "text",
    media_path: Optional[str] = None,
    media_mime_type: Optional[str] = None,
    media_caption: Optional[str] = None,
    transcription: Optional[str] = None,
) -> Message:
    """Save a message to the database."""
    msg = Message(
        conversation_id=conversation_id,
        content=content,
        direction=direction,
        ai_generated=ai_generated,
        status=status,
        whatsapp_message_id=whatsapp_message_id,
        message_type=message_type,
        media_path=media_path,
        media_mime_type=media_mime_type,
        media_caption=media_caption,
        transcription=transcription,
    )
    db.add(msg)

    # Update conversation's last_message_at
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.last_message_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)
    return msg


def get_conversation_history(
    db: Session,
    conversation_id: str,
    limit: int = 15
) -> List[Dict]:
    """Get recent conversation history for AI context."""
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )

    # Reverse to chronological order
    messages = list(reversed(messages))

    history = []
    for msg in messages:
        role = "incoming" if msg.direction == MessageDirection.incoming else "outgoing"
        # Include media context in conversation history
        if msg.message_type == "image":
            text = msg.media_caption or msg.content or "[User sent an image]"
            if msg.transcription:
                text = f"[Image description: {msg.transcription}] {text}"
        elif msg.message_type == "audio":
            text = msg.transcription or msg.content or "[User sent a voice note]"
        else:
            text = msg.content or ""
        history.append({"role": role, "content": text})

    return history


async def process_incoming_message(
    account_id: str,
    sender: str,
    content: str,
    is_group: bool,
    message_id: Optional[str] = None,
    ws_callback=None,
    media_path: Optional[str] = None,
    media_type: str = "text",
    mime_type: Optional[str] = None,
    caption: Optional[str] = None,
) -> Optional[str]:
    """
    Full message processing pipeline:
    1. Save incoming message
    2. Check AI settings
    3. Get conversation history
    4. Generate AI reply
    5. Return reply text (caller sends via WhatsApp)
    """
    db = SessionLocal()
    try:
        # Get account
        account = db.query(WhatsAppAccount).filter(
            WhatsAppAccount.id == account_id
        ).first()
        if not account:
            logger.error(f"Account {account_id} not found")
            return None

        # Get or create bot settings
        bot_settings = db.query(BotSettings).filter(
            BotSettings.whatsapp_account_id == account_id
        ).first()
        if not bot_settings:
            bot_settings = BotSettings(whatsapp_account_id=account_id)
            db.add(bot_settings)
            db.commit()
            db.refresh(bot_settings)

        # Check if we should respond to groups
        if is_group and not bot_settings.respond_to_groups:
            logger.debug(f"Skipping group message from {sender}")
            return None

        # Get or create contact and conversation
        contact = get_or_create_contact(db, account_id, sender)

        # Check if contact is blocked
        if contact.blocked:
            logger.debug(f"Contact {sender} is blocked, skipping")
            return None

        conv = get_or_create_conversation(db, account_id, contact.id)

        # Save incoming message
        saved_msg = save_message(
            db=db,
            conversation_id=conv.id,
            content=content,
            direction=MessageDirection.incoming,
            ai_generated=False,
            status=MessageStatus.delivered,
            whatsapp_message_id=message_id,
            message_type=media_type,
            media_path=media_path,
            media_mime_type=mime_type,
            media_caption=caption,
        )

        # Emit WebSocket event for incoming message
        if ws_callback:
            msg_data = {
                "id": saved_msg.id,
                "conversation_id": conv.id,
                "account_id": account_id,
                "direction": "incoming",
                "content": content,
                "sender": sender,
                "created_at": saved_msg.created_at.isoformat(),
                "contact": {
                    "id": contact.id,
                    "name": contact.name,
                    "phone": contact.phone_number,
                },
            }
            await ws_callback("message_received", msg_data, account.user_id)

        # Check if AI should respond
        if not bot_settings.enabled:
            logger.debug("AI auto-reply is disabled")
            return None

        if conv.human_takeover:
            logger.debug(f"Human takeover active for conversation {conv.id}")
            return None

        if not contact.ai_enabled:
            logger.debug(f"AI disabled for contact {contact.id}")
            return None

        # Emit AI reply started event
        if ws_callback:
            await ws_callback(
                "ai_reply_started",
                {"conversation_id": conv.id, "account_id": account_id},
                account.user_id
            )

        # Get conversation history (exclude the just-saved message)
        history = get_conversation_history(db, conv.id, limit=15)
        # Remove the last message since we'll pass it separately
        if history and history[-1]["content"] == content:
            history = history[:-1]

        # Generate AI reply
        try:
            if media_path and media_type in ("image", "audio"):
                # Read media bytes for multimodal AI processing
                import aiofiles
                try:
                    async with aiofiles.open(media_path, 'rb') as f:
                        media_bytes = await f.read()
                except Exception as e:
                    logger.error(f"Failed to read media file {media_path}: {e}")
                    media_bytes = None

                if media_bytes and mime_type:
                    reply = await gemini_service.generate_multimodal_reply(
                        system_prompt=bot_settings.system_prompt,
                        conversation_history=history,
                        user_message=content or "",
                        media_bytes=media_bytes,
                        mime_type=mime_type.split(';')[0].strip(),
                        caption=caption,
                        max_length=bot_settings.max_reply_length,
                        language=bot_settings.language,
                    )
                else:
                    # Fallback to text reply if media couldn't be read
                    reply = await gemini_service.generate_reply(
                        system_prompt=bot_settings.system_prompt,
                        conversation_history=history,
                        user_message=content or "[Media message]",
                        max_length=bot_settings.max_reply_length,
                        language=bot_settings.language,
                    )
            else:
                reply = await gemini_service.generate_reply(
                    system_prompt=bot_settings.system_prompt,
                    conversation_history=history,
                    user_message=content,
                    max_length=bot_settings.max_reply_length,
                    language=bot_settings.language,
                )
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            if ws_callback:
                await ws_callback(
                    "ai_reply_error",
                    {"conversation_id": conv.id, "error": str(e)},
                    account.user_id
                )
            return None

        if not reply:
            logger.warning("Gemini returned empty reply")
            return None

        # Save AI reply
        ai_msg = save_message(
            db=db,
            conversation_id=conv.id,
            content=reply,
            direction=MessageDirection.outgoing,
            ai_generated=True,
            status=MessageStatus.pending,
        )

        # Emit AI reply completed event
        if ws_callback:
            await ws_callback(
                "ai_reply_completed",
                {
                    "id": ai_msg.id,
                    "conversation_id": conv.id,
                    "account_id": account_id,
                    "content": reply,
                    "ai_generated": True,
                    "direction": "outgoing",
                    "created_at": ai_msg.created_at.isoformat(),
                },
                account.user_id
            )

        return reply

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        return None
    finally:
        db.close()


async def update_outgoing_message_status(
    account_id: str,
    conversation_id: str,
    message_content: str,
    success: bool
):
    """Update the status of a sent message."""
    db = SessionLocal()
    try:
        msg = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.content == message_content,
                Message.direction == MessageDirection.outgoing,
                Message.status == MessageStatus.pending,
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        if msg:
            msg.status = MessageStatus.sent if success else MessageStatus.failed
            db.commit()
    except Exception as e:
        logger.error(f"Error updating message status: {e}")
    finally:
        db.close()
