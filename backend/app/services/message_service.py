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
from app.services.gemini_service import gemini_service, parse_dual_track_reply
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

        # Retrieve active knowledge base documents context for this account
        from app.services.document_service import get_active_knowledge_context
        from app.services.tts_service import generate_voice_note
        knowledge_context = get_active_knowledge_context(db, account_id)

        # Check if user requested a sticker from an image
        stickers_enabled = getattr(bot_settings, "stickers_enabled", True)
        if stickers_enabled and media_type == "image" and media_path:
            text_trigger = (caption or content or "").strip().lower()
            is_sticker_req = any(kw in text_trigger for kw in [
                "sticker", "stiker", "!sticker", "/sticker", "#sticker",
                "ஸ்டிக்கர்", "make sticker", "convert sticker"
            ])
            if is_sticker_req:
                logger.info(f"Sticker conversion requested for image {media_path}")
                ai_msg = save_message(
                    db=db,
                    conversation_id=conv.id,
                    content="[Sticker]",
                    direction=MessageDirection.outgoing,
                    ai_generated=True,
                    status=MessageStatus.pending,
                    message_type="sticker",
                    media_path=media_path,
                )
                if ws_callback:
                    await ws_callback(
                        "ai_reply_completed",
                        {
                            "id": ai_msg.id,
                            "conversation_id": conv.id,
                            "account_id": account_id,
                            "content": "[Sticker]",
                            "ai_generated": True,
                            "direction": "outgoing",
                            "message_type": "sticker",
                            "created_at": ai_msg.created_at.isoformat(),
                        },
                        account.user_id,
                    )
                return {
                    "reply": "[Sticker]",
                    "sticker_path": media_path,
                    "conversation_id": conv.id,
                    "message_id": ai_msg.id,
                }

        # Generate AI reply
        try:
            enable_web_search = getattr(bot_settings, "web_search_enabled", True)

            # 1. If incoming message is audio, first try high-speed Groq Whisper transcription
            transcribed_audio_text = None
            if media_type == "audio" and media_path:
                try:
                    from app.services.groq_service import transcribe_audio_groq
                    groq_key = getattr(bot_settings, "groq_api_key", None)
                    transcribed_audio_text = await transcribe_audio_groq(
                        audio_path=media_path,
                        groq_api_key=groq_key,
                        language=bot_settings.language,
                    )
                    if transcribed_audio_text:
                        logger.info(f"Incoming audio successfully transcribed: '{transcribed_audio_text}'")
                        content = f"[Voice Note: {transcribed_audio_text}]"
                        saved_msg.content = content
                        db.commit()
                except Exception as t_err:
                    logger.warning(f"Voice transcription attempt failed: {t_err}")

            # Determine if voice reply will be sent
            voice_active = getattr(bot_settings, "voice_reply_enabled", False) and (
                media_type == "audio" or getattr(bot_settings, "voice_reply_mode", "audio_only") == "always"
            )
            effective_system_prompt = bot_settings.system_prompt
            if voice_active:
                effective_system_prompt += (
                    "\n\n## 🎙️ VOICE NOTE SPEECH GUIDELINES\n"
                    "- This response will be synthesized and sent as a WhatsApp voice note.\n"
                    "- Match the user's language strictly: If the user spoke English, reply in natural, smooth, conversational English. If the user spoke Tamil, reply in Tamil. Never use awkward robotic phonetics.\n"
                    "- Speak like a real human friend talking naturally. Keep sentences flowing smoothly, relaxed, and easy to understand.\n"
                    "- Do NOT announce the clock time or say 'the time is ...' unless the user explicitly asked for the time.\n"
                    "- Do NOT use markdown asterisks (*), hashtags, bullet points, or list numbering."
                )

            if transcribed_audio_text:
                # Transcribed cleanly! Use standard text prompt with the actual words spoken
                reply = await gemini_service.generate_reply(
                    system_prompt=effective_system_prompt,
                    conversation_history=history,
                    user_message=transcribed_audio_text,
                    max_length=bot_settings.max_reply_length,
                    language=bot_settings.language,
                    knowledge_context=knowledge_context,
                    is_voice_output=voice_active,
                    enable_web_search=enable_web_search,
                )
            elif media_path and media_type in ("image", "audio"):
                # Read media bytes for multimodal AI processing
                import aiofiles
                try:
                    async with aiofiles.open(media_path, 'rb') as f:
                        media_bytes = await f.read()
                except Exception as e:
                    logger.error(f"Failed to read media file {media_path}: {e}")
                    media_bytes = None

                if media_bytes and mime_type:
                    try:
                        reply = await gemini_service.generate_multimodal_reply(
                            system_prompt=effective_system_prompt,
                            conversation_history=history,
                            user_message=content or "",
                            media_bytes=media_bytes,
                            mime_type=mime_type.split(';')[0].strip(),
                            caption=caption,
                            max_length=bot_settings.max_reply_length,
                            language=bot_settings.language,
                            knowledge_context=knowledge_context,
                            is_voice_output=voice_active,
                            enable_web_search=enable_web_search,
                        )
                    except Exception as mm_err:
                        logger.warning(f"Multimodal media processing failed: {mm_err}, falling back to text prompt")
                        fallback_prompt = "[User sent a voice note, but it could not be processed. Please reply politely asking them to repeat or send text.]" if media_type == "audio" else "[User sent an image]"
                        reply = await gemini_service.generate_reply(
                            system_prompt=effective_system_prompt,
                            conversation_history=history,
                            user_message=content or fallback_prompt,
                            max_length=bot_settings.max_reply_length,
                            language=bot_settings.language,
                            knowledge_context=knowledge_context,
                            is_voice_output=voice_active,
                            enable_web_search=enable_web_search,
                        )
                else:
                    # Fallback to text reply if media couldn't be read
                    fallback_prompt = "[User sent a voice note. Please ask them politely to repeat or type their message.]" if media_type == "audio" else "[Media message]"
                    reply = await gemini_service.generate_reply(
                        system_prompt=effective_system_prompt,
                        conversation_history=history,
                        user_message=content or fallback_prompt,
                        max_length=bot_settings.max_reply_length,
                        language=bot_settings.language,
                        knowledge_context=knowledge_context,
                        is_voice_output=voice_active,
                        enable_web_search=enable_web_search,
                    )
            else:
                reply = await gemini_service.generate_reply(
                    system_prompt=effective_system_prompt,
                    conversation_history=history,
                    user_message=content,
                    max_length=bot_settings.max_reply_length,
                    language=bot_settings.language,
                    knowledge_context=knowledge_context,
                    is_voice_output=voice_active,
                    enable_web_search=enable_web_search,
                )
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            if ws_callback:
                await ws_callback(
                    "ai_reply_error",
                    {"conversation_id": conv.id, "error": str(e)},
                    account.user_id
                )
            # If it's an audio message, provide a safe friendly fallback instead of total silence
            if media_type == "audio":
                reply = "I received your voice note, but couldn't process it right now. Please feel free to text your message!"
            else:
                return None

        if not reply and media_type == "audio":
            reply = "I'm sorry, I couldn't hear or understand the voice note clearly. Could you please send it again or type your message?"

        if not reply:
            logger.warning("Gemini returned empty reply")
            return None

        # Parse dual-track reply: display_text (for screen) vs speech_text (for audio synthesis)
        display_text, speech_text = parse_dual_track_reply(reply)

        # Check if Voice Note output is requested and enabled
        audio_path = None
        if getattr(bot_settings, "voice_reply_enabled", False):
            should_voice = (media_type == "audio") or (getattr(bot_settings, "voice_reply_mode", "audio_only") == "always")
            if should_voice:
                try:
                    import os
                    import uuid
                    from app.config import settings
                    tts_dir = os.path.join(settings.media_dir, account_id, "tts")
                    os.makedirs(tts_dir, exist_ok=True)
                    target_audio = os.path.join(tts_dir, f"voice_{uuid.uuid4().hex[:8]}.ogg")
                    voice_name = getattr(bot_settings, "voice_name", "en-IN-PrabhatNeural")
                    audio_path = await generate_voice_note(
                        text=speech_text,
                        voice_name=voice_name,
                        output_path=target_audio,
                        groq_api_key=getattr(bot_settings, "groq_api_key", None),
                    )
                except Exception as tts_err:
                    logger.error(f"Voice note generation failed: {tts_err}")
                    audio_path = None

        # Save AI reply
        ai_msg = save_message(
            db=db,
            conversation_id=conv.id,
            content=display_text,
            direction=MessageDirection.outgoing,
            ai_generated=True,
            status=MessageStatus.pending,
            message_type="audio" if audio_path else "text",
            media_path=audio_path,
        )

        # Emit AI reply completed event
        if ws_callback:
            await ws_callback(
                "ai_reply_completed",
                {
                    "id": ai_msg.id,
                    "conversation_id": conv.id,
                    "account_id": account_id,
                    "content": display_text,
                    "ai_generated": True,
                    "direction": "outgoing",
                    "message_type": "audio" if audio_path else "text",
                    "created_at": ai_msg.created_at.isoformat(),
                },
                account.user_id
            )

        return {
            "reply": display_text,
            "speech_text": speech_text,
            "audio_path": audio_path,
            "conversation_id": conv.id,
            "message_id": ai_msg.id,
        }

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        return None
    finally:
        db.close()


async def update_outgoing_message_status(
    account_id: str,
    conversation_id: str,
    message_content: Optional[str] = None,
    success: bool = True,
    message_id: Optional[str] = None,
):
    """Update the status of a sent message."""
    db = SessionLocal()
    try:
        query = db.query(Message).filter(Message.conversation_id == conversation_id)
        if message_id:
            msg = query.filter(Message.id == message_id).first()
        else:
            msg = (
                query.filter(
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
            logger.info(f"Updated message {msg.id} status to {msg.status}")
    except Exception as e:
        logger.error(f"Error updating message status: {e}")
    finally:
        db.close()
