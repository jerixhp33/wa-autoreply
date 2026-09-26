import os
import logging
import asyncio
import shutil
import tempfile
import httpx
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_groq_api_key(override_key: Optional[str] = None) -> Optional[str]:
    """Get the active Groq API key from override, settings, or env."""
    if override_key and override_key.strip():
        return override_key.strip()
    if getattr(settings, "groq_api_key", None) and settings.groq_api_key.strip():
        return settings.groq_api_key.strip()
    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    return env_key if env_key else None


async def transcribe_audio_groq(
    audio_path: str,
    groq_api_key: Optional[str] = None,
    language: Optional[str] = None,
) -> Optional[str]:
    """
    Transcribe an incoming voice note using Groq Whisper (whisper-large-v3).
    Lightning fast (~150ms) and highly accurate across English, Tamil, Hindi, etc.
    """
    api_key = get_groq_api_key(groq_api_key)
    if not api_key:
        logger.debug("No Groq API key configured; skipping Groq Whisper transcription")
        return None

    if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
        logger.warning(f"Audio file missing or empty: {audio_path}")
        return None

    url = f"{GROQ_BASE_URL}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        filename = os.path.basename(audio_path)
        # Determine MIME type based on extension
        mime = "audio/ogg"
        if filename.endswith(".mp3"):
            mime = "audio/mpeg"
        elif filename.endswith(".wav"):
            mime = "audio/wav"
        elif filename.endswith(".m4a"):
            mime = "audio/m4a"

        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(audio_path, "rb") as f:
                file_content = f.read()

            files = {"file": (filename, file_content, mime)}
            data = {
                "model": "whisper-large-v3",
                "response_format": "json",
            }
            if language and language != "automatic":
                # Supply ISO-639-1 code if known
                lang_code = {
                    "english": "en",
                    "tamil": "ta",
                    "tanglish": "ta",
                    "hindi": "hi",
                    "spanish": "es",
                    "french": "fr",
                }.get(language.lower())
                if lang_code:
                    data["language"] = lang_code

            logger.info(f"Sending audio ({len(file_content)} bytes) to Groq Whisper...")
            resp = await client.post(url, headers=headers, data=data, files=files)

            if resp.status_code == 200:
                result = resp.json()
                text = result.get("text", "").strip()
                logger.info(f"Groq Whisper transcription success: '{text}'")
                return text
            else:
                logger.warning(f"Groq Whisper transcription failed ({resp.status_code}): {resp.text}")
                return None
    except Exception as e:
        logger.error(f"Error during Groq audio transcription: {e}", exc_info=True)
        return None


async def generate_speech_groq(
    text: str,
    voice: str = "Fritz-PlayAI",
    groq_api_key: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Optional[str]:
    """
    Generate speech using Groq's PlayAI TTS model (playai-tts),
    and transcode the output to WhatsApp-compliant 16kHz mono OGG Opus.
    """
    api_key = get_groq_api_key(groq_api_key)
    if not api_key:
        logger.debug("No Groq API key configured; skipping Groq TTS")
        return None

    clean_text = text.strip()
    if not clean_text:
        return None

    # Strip markdown and excessive emojis for cleaner speech
    import re
    clean_text = re.sub(r'[*_~`#\[\]]', '', clean_text)
    clean_text = re.sub(r'http\S+', '', clean_text)
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    url = f"{GROQ_BASE_URL}/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "playai-tts",
        "input": clean_text,
        "voice": voice,
        "response_format": "wav",
    }

    try:
        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".ogg")
            os.close(fd)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        fd, temp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        async with httpx.AsyncClient(timeout=40.0) as client:
            logger.info(f"Requesting Groq PlayAI TTS for text ({len(clean_text)} chars, voice: {voice})...")
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code != 200:
                logger.warning(f"Groq TTS failed ({resp.status_code}): {resp.text}")
                return None

            with open(temp_wav, "wb") as f:
                f.write(resp.content)

        if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
            logger.warning("Groq TTS returned empty audio payload")
            return None

        # Transcode WAV to WhatsApp PTT Opus OGG (mono, 16kHz, libopus)
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin,
                "-y",
                "-i", temp_wav,
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
                logger.warning(f"ffmpeg conversion failed ({proc.returncode}): {stderr.decode(errors='ignore')}")
                shutil.copy(temp_wav, output_path)
            else:
                logger.info(f"Transcoded Groq TTS to WhatsApp Opus: {output_path} ({os.path.getsize(output_path)} bytes)")
        else:
            logger.warning("ffmpeg not found, copying raw WAV")
            shutil.copy(temp_wav, output_path)

        try:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception:
            pass

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
        return None

    except Exception as e:
        logger.error(f"Failed to generate Groq TTS audio: {e}", exc_info=True)
        return None
