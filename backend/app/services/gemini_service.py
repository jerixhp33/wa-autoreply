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

        # Build full system instruction
        full_system = system_prompt.strip()
        full_system = full_system.replace('{current_time}', current_time)
        full_system = full_system.replace('{current_date}', current_date)
        full_system += f"\n\n## LIVE DATETIME\nCurrent IST Time: {current_time}\nCurrent Date: {current_date}\nAlways use this when user asks about time or date."

        if knowledge_context:
            full_system += f"\n\n## VERIFIED BUSINESS KNOWLEDGE BASE\nUse the following official business documents to answer customer questions accurately:\n{knowledge_context}\nAnswer strictly based on this knowledge. Never invent prices, products, or policies."

        if language and language != "automatic":
            full_system += f"\n\nAlways respond in: {language}."
        if max_length and max_length > 0:
            full_system += f"\n\nKeep your reply under {max_length} characters."

        # Build content list from conversation history
        # Neonize gives us role="incoming" (user) or "outgoing" (model)
        contents: List[types.Content] = []

        for msg in conversation_history:
            gemini_role = "user" if msg["role"] == "incoming" else "model"
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=msg["content"])],
                )
            )

        # Add the new user message
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=user_message)],
            )
        )

        config = types.GenerateContentConfig(
            system_instruction=full_system,
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

        # Build full system instruction
        full_system = system_prompt.strip()
        full_system = full_system.replace('{current_time}', current_time)
        full_system = full_system.replace('{current_date}', current_date)
        full_system += f"\n\n## LIVE DATETIME\nCurrent IST Time: {current_time}\nCurrent Date: {current_date}\nAlways use this when user asks about time or date."

        if knowledge_context:
            full_system += f"\n\n## VERIFIED BUSINESS KNOWLEDGE BASE\nUse the following official business documents to answer customer questions accurately:\n{knowledge_context}\nAnswer strictly based on this knowledge. Never invent prices, products, or policies."

        if language and language != "automatic":
            full_system += f"\n\nAlways respond in: {language}."
        if max_length and max_length > 0:
            full_system += f"\n\nKeep your reply under {max_length} characters."

        # Build content list from conversation history
        contents: List[types.Content] = []

        for msg in conversation_history:
            gemini_role = "user" if msg["role"] == "incoming" else "model"
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=msg["content"])],
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

        config = types.GenerateContentConfig(
            system_instruction=full_system,
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
