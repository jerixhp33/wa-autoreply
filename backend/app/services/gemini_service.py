"""
Gemini AI Service

Uses the official google-genai SDK (v2.x) to generate WhatsApp replies.
Supports async via client.aio.models.generate_content.
Includes retry logic with exponential backoff for transient errors.
"""
import asyncio
import logging
from typing import List, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0  # Doubles each retry: 1s, 2s, 4s


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    error_str = str(error).lower()
    # 503 Service Unavailable, 429 Rate Limit, connection errors
    retryable_codes = ["503", "429", "unavailable", "resource_exhausted", "too many requests"]
    return any(code in error_str for code in retryable_codes)


def parse_dual_track_reply(raw_text: str) -> tuple:
    """
    Parses dual-track response if present:
    ---DISPLAY---
    <display_text>
    ---SPEECH---
    <speech_text>
    Returns (display_text, speech_text).
    """
    if not raw_text:
        return ("", "")

    raw = raw_text.strip()
    import re
    # Match various divider forms: ---SPEECH---, ### SPEECH, **SPEECH:**, etc.
    speech_match = re.search(r'[-#* ]*---?\s*SPEECH\s*---?[-#* :]*', raw, re.IGNORECASE)
    if speech_match:
        display_part = raw[:speech_match.start()]
        speech_part = raw[speech_match.end():]
        display_part = re.sub(r'[-#* ]*---?\s*DISPLAY\s*---?[-#* :]*', '', display_part, flags=re.IGNORECASE).strip()
        speech_part = speech_part.strip()
        return (display_part or raw, speech_part or display_part)

    display_match = re.search(r'[-#* ]*---?\s*DISPLAY\s*---?[-#* :]*', raw, re.IGNORECASE)
    if display_match:
        display_part = raw[display_match.end():].strip()
        return (display_part, display_part)

    return (raw, raw)


class GeminiService:
    """Service for generating AI replies using Google Gemini."""

    def __init__(self):
        self._client = None
        self.model = settings.gemini_model

    def _get_client(self):
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            if not settings.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY is not set. "
                    "Add it to your .env file to enable AI replies."
                )
            from google import genai
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    async def generate_reply(
        self,
        system_prompt: str,
        conversation_history: List[Dict],
        user_message: str,
        max_length: int = 500,
        language: str = "automatic",
        knowledge_context: Optional[str] = None,
        is_voice_output: bool = False,
        enable_web_search: bool = True,
    ) -> Optional[str]:
        """
        Generate an AI reply.

        Args:
            system_prompt:        The AI persona/instructions.
            conversation_history: List of {"role": "incoming"|"outgoing", "content": str}
                                  representing the last 10-15 messages (oldest first).
            user_message:         The new incoming customer message.
            max_length:           Character limit for the reply.
            language:             Language override (e.g. "english", "tamil", "automatic").
            knowledge_context:    Business knowledge base documents text.
            is_voice_output:      Whether this reply will be synthesized into an audio voice note.

        Returns:
            The generated reply string, or None on failure.
        """
        from google.genai import types

        try:
            client = self._get_client()
        except ValueError as e:
            logger.error(str(e))
            return None

        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        current_time = now_ist.strftime('%I:%M %p IST')
        current_date = now_ist.strftime('%A, %B %d, %Y')
        hour = now_ist.hour
        if 5 <= hour < 12:
            time_of_day = "Morning"
        elif 12 <= hour < 17:
            time_of_day = "Afternoon"
        elif 17 <= hour < 21:
            time_of_day = "Evening"
        else:
            time_of_day = "Night"

        # Build full system instruction
        full_system = system_prompt.strip()
        full_system = full_system.replace('{current_time}', current_time)
        full_system = full_system.replace('{current_date}', current_date)
        full_system += f"\n\n## LIVE DATETIME\nCurrent IST Time: {current_time} ({time_of_day})\nCurrent Date: {current_date}\nCurrent Period: {time_of_day}\nMatch greetings to {time_of_day} (e.g. do not say good night or midnight if it is daytime)."

        if knowledge_context:
            full_system += f"\n\n## VERIFIED BUSINESS KNOWLEDGE BASE\nUse the following official business documents to answer customer questions accurately:\n{knowledge_context}\nAnswer strictly based on this knowledge. Never invent prices, products, or policies."

        if language and language != "automatic":
            full_system += f"\n\nAlways respond in: {language}."
        if max_length and max_length > 0:
            full_system += f"\n\nKeep your reply under {max_length} characters."

        if is_voice_output:
            full_system += (
                "\n\n## 🎙️ DUAL-TRACK OUTPUT REQUIREMENT (CRITICAL)\n"
                "Format your output with two sections using these exact headers:\n"
                "---DISPLAY---\n"
                "<The reply text shown on the WhatsApp chat screen. Can use casual Tanglish or English, line breaks, and aesthetic emojis.>\n"
                "---SPEECH---\n"
                "<The exact words to be spoken in the audio voice note. Follow these strict speech rules:\n"
                "1. If the message is in Tamil or Tanglish, write this SPEECH section in fluent spoken TAMIL SCRIPT (தமிழ் எழுத்துக்கள்) so the native Tamil voice synthesizer pronounces every word smoothly and authentically (e.g. 'வணக்கம்! எப்படி இருக்கீங்க? சொல்லுங்க, நான் உங்களுக்கு எப்படி ஹெல்ப் பண்ணட்டும்?'). NEVER use English Latin letters for Tamil words in the speech track.\n"
                "2. ALWAYS use natural spoken colloquial Tamil (பேச்சுத் தமிழ்). NEVER write formal or literary written Tamil (எழுத்துத் தமிழ்), which sounds stiff and robotic on TTS:\n"
                "   * Use 'பண்றேன்' (NEVER 'செய்கிறேன்') | 'பண்ணுங்க' (NEVER 'செய்யுங்கள்')\n"
                "   * Use 'வர்றேன்' (NEVER 'வருகிறேன்') | 'வாடா / வாங்க' (NEVER 'வாருங்கள்')\n"
                "   * Use 'போறேன்' (NEVER 'செல்கிறேன்') | 'போங்க' (NEVER 'செல்லுங்கள்')\n"
                "   * Use 'இருக்கீங்க' (NEVER 'இருக்கிறீர்கள்') | 'இருக்கேன்' (NEVER 'இருக்கிறேன்')\n"
                "   * Use 'சாப்டியா?' (NEVER 'சாப்பிட்டாயா?') | 'சாப்பிட்டேன்' (NEVER 'உணவு உண்டேன்')\n"
                "   * Use 'சொல்லுங்க' (NEVER 'கூறுங்கள்') | 'கேளுங்க' (NEVER 'கேளுங்கள்')\n"
                "   * Use 'புரியுது' (NEVER 'புரிகிறது') | 'தெரியும்' (NEVER 'தெரியவருகிறது')\n"
                "   * Use 'கண்டிப்பா' (NEVER 'நிச்சயமாக') | 'ரொம்ப' (NEVER 'மிகவும்')\n"
                "   * Use 'எப்படி இருக்கீங்க?' (NEVER 'எவ்வாறு உள்ளீர்கள்?')\n"
                "3. Transliterate common English loanwords into Tamil script phonetically so the native voice pronounces them naturally ('ஹெல்ப்', 'வாட்ஸ்அப்', 'மெசேஜ்', 'ஆபீஸ்', 'டைம்', 'காபி', 'பிசி', 'ரிலாக்ஸ்', 'சூப்பர்').\n"
                "4. If the message is in English, write in natural, conversational English.\n"
                "5. ZERO emojis, ZERO asterisks (*), ZERO bullet points, ZERO unprompted clock announcements. Use natural commas and periods for breath pauses.>"
            )

        # Build content list from conversation history
        # Neonize gives us role="incoming" (user) or "outgoing" (model)
        contents: List[types.Content] = []

        for msg in conversation_history:
            gemini_role = "user" if msg["role"] == "incoming" else "model"
            content_text = msg.get("content", "") or ""
            if gemini_role == "model":
                content_text, _ = parse_dual_track_reply(content_text)
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=content_text)],
                )
            )

        # Add the new user message
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=user_message)],
            )
        )

        # Google Search Grounding tools when enabled
        tools = None
        if enable_web_search:
            try:
                tools = [types.Tool(google_search=types.GoogleSearch())]
            except Exception as tool_err:
                logger.debug(f"Google search tool init note: {tool_err}")

        config = types.GenerateContentConfig(
            system_instruction=full_system,
            tools=tools,
            max_output_tokens=min(1024, max_length * 2 if max_length else 1024),
            temperature=0.7,
        )

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Use async client
                response = await client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                if not response or not response.text:
                    logger.warning("Gemini returned empty response")
                    return None

                reply = response.text.strip()

                # Enforce character limit
                if max_length and len(reply) > max_length:
                    # Try to cut at word boundary
                    truncated = reply[:max_length]
                    last_space = truncated.rfind(" ")
                    if last_space > max_length * 0.8:
                        truncated = truncated[:last_space]
                    reply = truncated + "…"

                return reply

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES and _is_retryable_error(e):
                    delay = BASE_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"Gemini API transient error (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                        f"retrying in {delay:.1f}s: {type(e).__name__}: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Gemini API error: {type(e).__name__}: {e}")
                    raise

        # Should not reach here, but just in case
        logger.error(f"Gemini API failed after {MAX_RETRIES + 1} attempts: {last_error}")
        raise last_error

    async def generate_multimodal_reply(
        self,
        system_prompt: str,
        conversation_history: List[Dict],
        user_message: str,
        media_bytes: bytes,
        mime_type: str,
        caption: str = None,
        max_length: int = 500,
        language: str = "automatic",
        knowledge_context: Optional[str] = None,
        is_voice_output: bool = False,
        enable_web_search: bool = True,
    ) -> Optional[str]:
        """
        Generate an AI reply for multimodal inputs (images, audio).
        """
        from google.genai import types

        try:
            client = self._get_client()
        except ValueError as e:
            logger.error(str(e))
            return None

        from datetime import datetime
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist)
        current_time = now_ist.strftime('%I:%M %p IST')
        current_date = now_ist.strftime('%A, %B %d, %Y')
        hour = now_ist.hour
        if 5 <= hour < 12:
            time_of_day = "Morning"
        elif 12 <= hour < 17:
            time_of_day = "Afternoon"
        elif 17 <= hour < 21:
            time_of_day = "Evening"
        else:
            time_of_day = "Night"

        # Build full system instruction
        full_system = system_prompt.strip()
        full_system = full_system.replace('{current_time}', current_time)
        full_system = full_system.replace('{current_date}', current_date)
        full_system += f"\n\n## LIVE DATETIME\nCurrent IST Time: {current_time} ({time_of_day})\nCurrent Date: {current_date}\nCurrent Period: {time_of_day}\nMatch greetings to {time_of_day} (e.g. do not say good night or midnight if it is daytime)."

        if knowledge_context:
            full_system += f"\n\n## VERIFIED BUSINESS KNOWLEDGE BASE\nUse the following official business documents to answer customer questions accurately:\n{knowledge_context}\nAnswer strictly based on this knowledge. Never invent prices, products, or policies."

        if language and language != "automatic":
            full_system += f"\n\nAlways respond in: {language}."
        if max_length and max_length > 0:
            full_system += f"\n\nKeep your reply under {max_length} characters."

        if is_voice_output:
            full_system += (
                "\n\n## 🎙️ DUAL-TRACK OUTPUT REQUIREMENT (CRITICAL)\n"
                "Format your output with two sections using these exact headers:\n"
                "---DISPLAY---\n"
                "<The reply text shown on the WhatsApp chat screen. Can use casual Tanglish or English, line breaks, and aesthetic emojis.>\n"
                "---SPEECH---\n"
                "<The exact words to be spoken in the audio voice note. Follow these strict speech rules:\n"
                "1. If the message is in Tamil or Tanglish, write this SPEECH section in fluent spoken TAMIL SCRIPT (தமிழ் எழுத்துக்கள்) so the native Tamil voice synthesizer pronounces every word smoothly and authentically (e.g. 'வணக்கம்! எப்படி இருக்கீங்க? சொல்லுங்க, நான் உங்களுக்கு எப்படி ஹெல்ப் பண்ணட்டும்?'). NEVER use English Latin letters for Tamil words in the speech track.\n"
                "2. ALWAYS use natural spoken colloquial Tamil (பேச்சுத் தமிழ்). NEVER write formal or literary written Tamil (எழுத்துத் தமிழ்), which sounds stiff and robotic on TTS:\n"
                "   * Use 'பண்றேன்' (NEVER 'செய்கிறேன்') | 'பண்ணுங்க' (NEVER 'செய்யுங்கள்')\n"
                "   * Use 'வர்றேன்' (NEVER 'வருகிறேன்') | 'வாடா / வாங்க' (NEVER 'வாருங்கள்')\n"
                "   * Use 'போறேன்' (NEVER 'செல்கிறேன்') | 'போங்க' (NEVER 'செல்லுங்கள்')\n"
                "   * Use 'இருக்கீங்க' (NEVER 'இருக்கிறீர்கள்') | 'இருக்கேன்' (NEVER 'இருக்கிறேன்')\n"
                "   * Use 'சாப்டியா?' (NEVER 'சாப்பிட்டாயா?') | 'சாப்பிட்டேன்' (NEVER 'உணவு உண்டேன்')\n"
                "   * Use 'சொல்லுங்க' (NEVER 'கூறுங்கள்') | 'கேளுங்க' (NEVER 'கேளுங்கள்')\n"
                "   * Use 'புரியுது' (NEVER 'புரிகிறது') | 'தெரியும்' (NEVER 'தெரியவருகிறது')\n"
                "   * Use 'கண்டிப்பா' (NEVER 'நிச்சயமாக') | 'ரொம்ப' (NEVER 'மிகவும்')\n"
                "   * Use 'எப்படி இருக்கீங்க?' (NEVER 'எவ்வாறு உள்ளீர்கள்?')\n"
                "3. Transliterate common English loanwords into Tamil script phonetically so the native voice pronounces them naturally ('ஹெல்ப்', 'வாட்ஸ்அப்', 'மெசேஜ்', 'ஆபீஸ்', 'டைம்', 'காபி', 'பிசி', 'ரிலாக்ஸ்', 'சூப்பர்').\n"
                "4. If the message is in English, write in natural, conversational English.\n"
                "5. ZERO emojis, ZERO asterisks (*), ZERO bullet points, ZERO unprompted clock announcements. Use natural commas and periods for breath pauses.>"
            )

        # Build content list from conversation history
        contents: List[types.Content] = []

        for msg in conversation_history:
            gemini_role = "user" if msg["role"] == "incoming" else "model"
            content_text = msg.get("content", "") or ""
            if gemini_role == "model":
                content_text, _ = parse_dual_track_reply(content_text)
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=content_text)],
                )
            )

        # Build parts for the final user message
        final_parts = []
        final_parts.append(types.Part.from_bytes(data=media_bytes, mime_type=mime_type))

        if caption:
            final_parts.append(types.Part(text=caption))

        if user_message and user_message not in (caption, "[Voice Note]", "[Image]"):
            final_parts.append(types.Part(text=user_message))

        if mime_type.startswith('audio/'):
            final_parts.append(types.Part(text="Listen to this voice note, understand what the user is saying, and reply to them naturally in the same language."))
        elif not caption and (not user_message or user_message == "[Image]"):
            final_parts.append(types.Part(text="What is this photo? Describe it and reply naturally."))

        contents.append(
            types.Content(
                role="user",
                parts=final_parts,
            )
        )

        tools = None
        if enable_web_search:
            try:
                tools = [types.Tool(google_search=types.GoogleSearch())]
            except Exception as tool_err:
                logger.debug(f"Google search tool init note: {tool_err}")

        config = types.GenerateContentConfig(
            system_instruction=full_system,
            tools=tools,
            max_output_tokens=min(1024, max_length * 2 if max_length else 1024),
            temperature=0.7,
        )

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Use async client
                response = await client.aio.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                if not response or not response.text:
                    logger.warning("Gemini returned empty response")
                    return None

                reply = response.text.strip()

                # Enforce character limit
                if max_length and len(reply) > max_length:
                    # Try to cut at word boundary
                    truncated = reply[:max_length]
                    last_space = truncated.rfind(" ")
                    if last_space > max_length * 0.8:
                        truncated = truncated[:last_space]
                    reply = truncated + "…"

                return reply

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES and _is_retryable_error(e):
                    delay = BASE_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        f"Gemini API transient error (attempt {attempt + 1}/{MAX_RETRIES + 1}), "
                        f"retrying in {delay:.1f}s: {type(e).__name__}: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Gemini API error: {type(e).__name__}: {e}")
                    raise

        # Should not reach here, but just in case
        logger.error(f"Gemini API failed after {MAX_RETRIES + 1} attempts: {last_error}")
        raise last_error


# Singleton
gemini_service = GeminiService()
