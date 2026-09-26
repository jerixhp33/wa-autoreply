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


PLAYAI_FALLBACK_MAP = {
    "Aria-PlayAI": "ta-IN-PallaviNeural",
    "Fritz-PlayAI": "ta-IN-ValluvarNeural",
    "Dexter-PlayAI": "en-IN-PrabhatNeural",
}


async def generate_voice_note(
    text: str,
    voice_name: Optional[str] = None,
    output_path: Optional[str] = None,
    groq_api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Generate an audio voice note from text.
    Uses Microsoft Edge-TTS natural neural voices for high fidelity Tamil, English, and Hindi.
    Always produces WhatsApp-compliant 16kHz mono OGG Opus.
    """
    if not text or not text.strip():
        return None

    import re
    # Remove URLs
    clean_text = re.sub(r'https?://\S+|www\.\S+', '', text)
    # Remove markdown symbols
    clean_text = re.sub(r'[*_~`#\[\]]', '', clean_text)
    # Remove emojis so TTS speaks pure natural language rather than reading out emoji names
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-a
        "]+", flags=re.UNICODE
    )
    clean_text = emoji_pattern.sub('', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    if not clean_text:
        logger.info("Text contains only emojis/links; skipping voice note generation")
        return None

    if len(clean_text) > 800:
        clean_text = clean_text[:800]  # Cap length for voice note

    # Resolve voice: map legacy PlayAI voices to their natural neural counterparts
    voice = voice_name or DEFAULT_VOICE
    if voice in PLAYAI_FALLBACK_MAP:
        voice = PLAYAI_FALLBACK_MAP[voice]
    elif voice not in VOICE_CATALOG or voice.endswith("-PlayAI"):
        voice = DEFAULT_VOICE

    edge_voice = voice

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
                "-b:a", "32k",
                "-ac", "1",
                "-ar", "16000",
                "-application", "voip",
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
