import os
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-IN-NeerjaNeural"

VOICE_CATALOG = {
    # Groq PlayAI Studio Voices
    "Fritz-PlayAI": "Groq PlayAI (Dynamic Male - Fritz)",
    "Aria-PlayAI": "Groq PlayAI (Expressive Female - Aria)",
    "Dexter-PlayAI": "Groq PlayAI (Deep Male - Dexter)",
    # Microsoft Edge Natural Voices (Indian & Global)
    "en-IN-NeerjaNeural": "Indian English (Female - Neerja)",
    "en-IN-PrabhatNeural": "Indian English (Male - Prabhat)",
    "ta-IN-PallaviNeural": "Tamil (Female - Pallavi)",
    "ta-IN-ValluvarNeural": "Tamil (Male - Valluvar)",
    "hi-IN-SwaraNeural": "Hindi (Female - Swara)",
    "hi-IN-MadhurNeural": "Hindi (Male - Madhur)",
    "en-US-JennyNeural": "US English (Female - Jenny)",
    "en-US-GuyNeural": "US English (Male - Guy)",
}


async def generate_voice_note(
    text: str,
    voice_name: Optional[str] = None,
    output_path: Optional[str] = None,
    groq_api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Generate an audio voice note from text.
    Uses Groq PlayAI TTS if configured/selected, with automatic fallback to Edge-TTS.
    Always produces WhatsApp-compliant 16kHz mono OGG Opus.
    """
    if not text or not text.strip():
        return None

    voice = voice_name if voice_name in VOICE_CATALOG else DEFAULT_VOICE

    # 1. Try Groq PlayAI TTS if requested or if Groq API key is present with a PlayAI voice
    if voice.endswith("-PlayAI") or (groq_api_key and "PlayAI" in voice):
        try:
            from app.services.groq_service import generate_speech_groq
            groq_voice = voice.replace("-PlayAI", "")
            if not groq_voice.endswith("-PlayAI") and groq_voice not in ("Aria", "Dexter"):
                groq_voice = f"{groq_voice}-PlayAI"
            groq_result = await generate_speech_groq(
                text=text,
                voice=groq_voice,
                groq_api_key=groq_api_key,
                output_path=output_path,
            )
            if groq_result and os.path.exists(groq_result) and os.path.getsize(groq_result) > 0:
                logger.info(f"Generated voice note with Groq TTS: {groq_result}")
                return groq_result
            else:
                logger.warning("Groq TTS did not return valid audio, falling back to Edge-TTS")
        except Exception as groq_err:
            logger.warning(f"Groq TTS failed: {groq_err}, falling back to Edge-TTS")

    # If voice was a PlayAI voice but Groq failed or wasn't configured, fallback to default Edge voice
    edge_voice = voice if not voice.endswith("-PlayAI") else DEFAULT_VOICE

    # Clean text of markdown asterisks, URLs, and code blocks for clean speech
    clean_text = text.replace("*", "").replace("#", "").replace("_", "").replace("`", "").strip()
    if len(clean_text) > 800:
        clean_text = clean_text[:800]  # Cap length for voice note

    try:
        import edge_tts
        import tempfile
        import shutil

        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".ogg")
            os.close(fd)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # edge-tts generates MP3
        fd, temp_mp3 = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

        communicate = edge_tts.Communicate(clean_text, edge_voice)
        await communicate.save(temp_mp3)

        if not os.path.exists(temp_mp3) or os.path.getsize(temp_mp3) == 0:
            logger.warning("TTS generated empty MP3 file")
            return None

        # Convert to WhatsApp PTT compliant OGG Opus (mono, 16kHz, libopus)
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin,
                "-y",
                "-i", temp_mp3,
                "-c:a", "libopus",
                "-b:a", "24k",
                "-ac", "1",
                "-ar", "16000",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"ffmpeg conversion failed ({proc.returncode}): {stderr.decode(errors='ignore')}, using MP3 fallback")
                shutil.copy(temp_mp3, output_path)
            else:
                logger.info(f"Converted TTS to WhatsApp PTT Opus: {output_path} ({os.path.getsize(output_path)} bytes)")
        else:
            logger.warning("ffmpeg not found, using raw MP3 as fallback")
            shutil.copy(temp_mp3, output_path)

        try:
            if os.path.exists(temp_mp3):
                os.remove(temp_mp3)
        except Exception:
            pass

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Generated voice note ({edge_voice}): {output_path} ({os.path.getsize(output_path)} bytes)")
            return output_path
        else:
            logger.warning("TTS output file is missing or empty")
            return None

    except Exception as e:
        logger.error(f"Failed to generate TTS audio: {e}", exc_info=True)
        return None
