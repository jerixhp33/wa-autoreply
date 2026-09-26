from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import WhatsAppAccount, BotSettings, User
from app.schemas.schemas import BotSettingsResponse, BotSettingsUpdate, VoicePreviewRequest
from app.services.auth_service import get_current_user
from app.services.tts_service import generate_voice_preview

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/settings", response_model=List[BotSettingsResponse])
async def get_all_bot_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.user_id == current_user.id
    ).all()
    account_ids = [a.id for a in accounts]

    settings_list = db.query(BotSettings).filter(
        BotSettings.whatsapp_account_id.in_(account_ids)
    ).all()

    return [BotSettingsResponse.model_validate(s) for s in settings_list]


@router.get("/settings/{account_id}", response_model=BotSettingsResponse)
async def get_bot_settings(
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

    bot_settings = db.query(BotSettings).filter(
        BotSettings.whatsapp_account_id == account_id
    ).first()
    if not bot_settings:
        bot_settings = BotSettings(whatsapp_account_id=account_id)
        db.add(bot_settings)
        db.commit()
        db.refresh(bot_settings)

    return BotSettingsResponse.model_validate(bot_settings)


@router.put("/settings/{account_id}", response_model=BotSettingsResponse)
async def update_bot_settings(
    account_id: str,
    data: BotSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(WhatsAppAccount).filter(
        WhatsAppAccount.id == account_id,
        WhatsAppAccount.user_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    bot_settings = db.query(BotSettings).filter(
        BotSettings.whatsapp_account_id == account_id
    ).first()
    if not bot_settings:
        bot_settings = BotSettings(whatsapp_account_id=account_id)
        db.add(bot_settings)

    if data.enabled is not None:
        bot_settings.enabled = data.enabled
    if data.system_prompt is not None:
        bot_settings.system_prompt = data.system_prompt
    if data.language is not None:
        bot_settings.language = data.language
    if data.max_reply_length is not None:
        bot_settings.max_reply_length = data.max_reply_length
    if data.respond_to_groups is not None:
        bot_settings.respond_to_groups = data.respond_to_groups
    if data.voice_reply_enabled is not None:
        bot_settings.voice_reply_enabled = data.voice_reply_enabled
    if data.voice_name is not None:
        bot_settings.voice_name = data.voice_name
    if data.voice_reply_mode is not None:
        bot_settings.voice_reply_mode = data.voice_reply_mode
    if data.groq_api_key is not None:
        bot_settings.groq_api_key = data.groq_api_key.strip() if data.groq_api_key else None

    try:
        db.commit()
        db.refresh(bot_settings)
    except Exception as commit_err:
        logger.warning(f"Initial commit failed (attempting schema auto-migration): {commit_err}")
        db.rollback()
        from sqlalchemy import text
        with db.bind.connect() as conn:
            conn.execute(text("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS voice_reply_enabled BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS voice_name VARCHAR DEFAULT 'en-IN-NeerjaNeural';"))
            conn.execute(text("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS voice_reply_mode VARCHAR DEFAULT 'audio_only';"))
            conn.execute(text("ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS groq_api_key VARCHAR;"))
            conn.commit()

        # Re-apply values and retry commit
        if data.enabled is not None:
            bot_settings.enabled = data.enabled
        if data.system_prompt is not None:
            bot_settings.system_prompt = data.system_prompt
        if data.language is not None:
            bot_settings.language = data.language
        if data.max_reply_length is not None:
            bot_settings.max_reply_length = data.max_reply_length
        if data.respond_to_groups is not None:
            bot_settings.respond_to_groups = data.respond_to_groups
        if data.voice_reply_enabled is not None:
            bot_settings.voice_reply_enabled = data.voice_reply_enabled
        if data.voice_name is not None:
            bot_settings.voice_name = data.voice_name
        if data.voice_reply_mode is not None:
            bot_settings.voice_reply_mode = data.voice_reply_mode

        db.commit()
        db.refresh(bot_settings)

    return BotSettingsResponse.model_validate(bot_settings)


@router.post("/tts/preview")
async def preview_voice(
    data: VoicePreviewRequest,
):
    """Generate audio preview bytes for testing a voice directly in the browser."""
    audio_bytes = await generate_voice_preview(
        voice_name=data.voice_name,
        sample_text=data.sample_text,
    )
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="Failed to synthesize voice preview")
    return Response(content=audio_bytes, media_type="audio/mpeg")
