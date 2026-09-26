import os
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-IN-NeerjaNeural"

VOICE_CATALOG = {
    "en-IN-NeerjaNeural": "Indian English (Female - Neerja)",
    "en-IN-PrabhatNeural": "Indian English (Male - Prabhat)",
    "en-US-JennyNeural": "US English (Female - Jenny)",
    "en-US-GuyNeural": "US English (Male - Guy)",
    "ta-IN-PallaviNeural": "Tamil (Female - Pallavi)",
    "ta-IN-ValluvarNeural": "Tamil (Male - Valluvar)",
    "hi-IN-SwaraNeural": "Hindi (Female - Swara)",
    "hi-IN-MadhurNeural": "Hindi (Male - Madhur)",
}


async def generate_voice_note(
    text: str,
    voice_name: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Optional[str]:
    """
    Generate an audio voice note from text using edge-tts.
    Returns the file path of the generated audio or None if failed.
    """
    if not text or not text.strip():
        return None

    voice = voice_name if voice_name in VOICE_CATALOG else DEFAULT_VOICE

    # Clean text of markdown asterisks, URLs, and code blocks for clean speech
    clean_text = text.replace("*", "").replace("#", "").replace("_", "").replace("`", "").strip()
    if len(clean_text) > 800:
        clean_text = clean_text[:800]  # Cap length for voice note

    try:
        import edge_tts

        if not output_path:
            import tempfile
            fd, output_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(output_path)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Generated voice note ({voice}): {output_path} ({os.path.getsize(output_path)} bytes)")
            return output_path
        else:
            logger.warning("TTS generated empty output file")
            return None

    except Exception as e:
        logger.error(f"Failed to generate TTS audio: {e}")
        return None
