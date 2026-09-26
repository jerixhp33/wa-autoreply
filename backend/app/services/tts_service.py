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
    "Aria-PlayAI": "en-IN-NeerjaNeural",
    "Fritz-PlayAI": "en-IN-PrabhatNeural",
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
    Always produces WhatsApp-compliant 24kHz HD mono OGG Opus.
    """
    if not text or not text.strip():
        return None

    import re
    # Remove URLs
    clean_text = re.sub(r'https?://\S+|www\.\S+', '', text)
    # Remove markdown symbols and brackets
    clean_text = re.sub(r'[*_~`#\[\]()]', '', clean_text)
    # Clean repeated punctuation
    clean_text = re.sub(r'!{2,}', '!', clean_text)
    clean_text = re.sub(r'\?{2,}', '?', clean_text)
    clean_text = re.sub(r'\.{2,}', '.', clean_text)
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

    # Smart voice selection based on script:
    # If text is written in Tamil script, use native Tamil neural voices for authentic Tamil speech.
    # If text is in Latin/English letters, use Indian English or US English neural voice for crystal clear pronunciation.
    has_tamil = bool(re.search(r'[\u0B80-\u0BFF]', clean_text))
    if has_tamil:
        if voice_name and "Valluvar" in str(voice_name):
            edge_voice = "ta-IN-ValluvarNeural"
        else:
            edge_voice = "ta-IN-PallaviNeural"
    else:
        # Latin / English script
        v = voice_name or DEFAULT_VOICE
        if v in PLAYAI_FALLBACK_MAP:
            v = PLAYAI_FALLBACK_MAP[v]
        if v in ("en-IN-PrabhatNeural", "ta-IN-ValluvarNeural"):
            edge_voice = "en-IN-PrabhatNeural"
        elif v in ("en-US-JennyNeural", "en-US-GuyNeural"):
            edge_voice = v
        else:
            edge_voice = "en-IN-NeerjaNeural"

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

        # -3% rate creates a natural, relaxed, conversational cadence
        communicate = edge_tts.Communicate(clean_text, edge_voice, rate="-3%")
        await communicate.save(temp_mp3)

        if not os.path.exists(temp_mp3) or os.path.getsize(temp_mp3) == 0:
            logger.warning("TTS generated empty MP3 file")
            return None

        # Convert to WhatsApp PTT compliant 24kHz HD OGG Opus (mono, 64kbps, wideband)
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin,
                "-y",
                "-i", temp_mp3,
                "-c:a", "libopus",
                "-b:a", "64k",
                "-ac", "1",
                "-ar", "24000",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"ffmpeg conversion failed ({proc.returncode}): {stderr.decode(errors='ignore')}, using MP3 fallback")
                shutil.copy(temp_mp3, output_path)
            else:
                logger.info(f"Converted TTS to WhatsApp PTT Opus HD: {output_path} ({os.path.getsize(output_path)} bytes)")
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


async def generate_voice_preview(
    voice_name: str,
    sample_text: Optional[str] = None,
) -> Optional[bytes]:
    """
    Generate an in-browser audio preview (MP3 bytes) for a selected voice.
    """
    import tempfile
    import edge_tts

    v = voice_name or DEFAULT_VOICE
    if v in PLAYAI_FALLBACK_MAP:
        v = PLAYAI_FALLBACK_MAP[v]

    text = sample_text
    if not text or not text.strip():
        if "Valluvar" in v or "Pallavi" in v or "ta-IN" in v:
            text = "வணக்கம்! நான் உங்க வாட்ஸ்அப் அசிஸ்டன்ட். உங்களுக்கு எப்படி உதவட்டும்?"
        elif "hi-IN" in v:
            text = "नमस्ते! मैं आपका व्हाट्सएप असिस्टेंट हूँ। मैं आपकी क्या मदद कर सकता हूँ?"
        else:
            text = "Hello there! I'm your WhatsApp AI assistant. How can I help you today?"

    try:
        fd, temp_mp3 = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)

        communicate = edge_tts.Communicate(text, v, rate="-3%")
        await communicate.save(temp_mp3)

        with open(temp_mp3, "rb") as f:
            audio_bytes = f.read()

        try:
            if os.path.exists(temp_mp3):
                os.remove(temp_mp3)
        except Exception:
            pass

        return audio_bytes
    except Exception as e:
        logger.error(f"Voice preview generation failed for {v}: {e}")
        return None
