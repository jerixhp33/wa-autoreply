"""
Contact Memory Service

Extracts and stores key facts about contacts from conversations using Gemini.
Injects relevant memories into AI system prompts for personalized replies.

This runs as fire-and-forget background work — it must NEVER block or crash
the main message processing flow.
"""
import json
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def extract_and_store_memories(
    contact_id: str,
    user_message: str,
    ai_reply: str,
):
    """
    Use Gemini to extract key facts from a conversation turn and store them.
    Creates its own DB session so the caller's session can close independently.
    This is designed to be called via asyncio.create_task (fire-and-forget).
    """
    try:
        from app.database.database import SessionLocal
        from app.models.models import ContactMemory
        from app.services.gemini_service import gemini_service
        from google.genai import types

        client = gemini_service._get_client()
        if not client:
            return

        extraction_prompt = (
            "You are a memory extraction agent. From the conversation below, "
            "extract any NEW noteworthy facts about the user. Focus on:\n"
            "- Their name (if mentioned)\n"
            "- Language preference (Tamil, English, Hindi, etc.)\n"
            "- Interests, hobbies, or topics they care about\n"
            "- Preferences (food, time, products, etc.)\n"
            "- Sentiment/mood (happy, frustrated, neutral)\n"
            "- Business needs (what they're looking for)\n\n"
            "Return ONLY a valid JSON array. Each item: "
            '{\"type\": \"preference|fact|topic|sentiment\", \"key\": \"short_key\", \"value\": \"brief description\"}\n'
            "If nothing noteworthy, return: []\n\n"
            f"USER MESSAGE: {user_message}\n"
            f"AI REPLY: {ai_reply}"
        )

        config = types.GenerateContentConfig(
            max_output_tokens=256,
            temperature=0.2,
        )

        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=extraction_prompt)])],
            config=config,
        )

        if not response or not response.text:
            return

        # Parse JSON from response
        raw = response.text.strip()
        # Handle markdown code blocks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        memories = json.loads(raw)
        if not isinstance(memories, list) or not memories:
            return

        # Store/upsert memories
        db = SessionLocal()
        try:
            for mem in memories[:5]:  # Cap at 5 per turn to prevent spam
                if not isinstance(mem, dict):
                    continue
                mem_type = mem.get("type", "fact")
                key = mem.get("key", "")
                value = mem.get("value", "")
                if not key or not value:
                    continue

                # Upsert: update existing memory with same key, or insert new
                existing = db.query(ContactMemory).filter(
                    ContactMemory.contact_id == contact_id,
                    ContactMemory.key == key,
                ).first()

                if existing:
                    existing.value = value
                    existing.memory_type = mem_type
                    logger.debug(f"Updated memory for contact {contact_id}: {key}={value}")
                else:
                    new_mem = ContactMemory(
                        contact_id=contact_id,
                        memory_type=mem_type,
                        key=key,
                        value=value,
                        confidence="high",
                    )
                    db.add(new_mem)
                    logger.info(f"💡 New memory for contact {contact_id}: {key}={value}")

            db.commit()
        except Exception as db_err:
            logger.warning(f"Memory storage error: {db_err}")
            db.rollback()
        finally:
            db.close()

    except json.JSONDecodeError:
        logger.debug(f"Memory extraction returned non-JSON, skipping")
    except Exception as e:
        logger.debug(f"Memory extraction error (non-critical): {e}")


def get_memory_context(contact_id: str, db: Session) -> str:
    """
    Build a memory context string for a contact to inject into the AI prompt.
    Returns empty string if no memories exist.
    """
    try:
        from app.models.models import ContactMemory

        memories = (
            db.query(ContactMemory)
            .filter(ContactMemory.contact_id == contact_id)
            .order_by(ContactMemory.updated_at.desc().nullslast(),
                      ContactMemory.created_at.desc())
            .limit(20)
            .all()
        )

        if not memories:
            return ""

        lines = ["## 🧠 KNOWN FACTS ABOUT THIS CONTACT (from previous conversations)"]
        for mem in memories:
            lines.append(f"- {mem.key}: {mem.value}")
        lines.append(
            "\nUse these facts to personalize your reply naturally. "
            "Don't explicitly say 'I remember you told me...' unless relevant."
        )

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Memory context retrieval error: {e}")
        return ""


async def clear_memories(contact_id: str):
    """Delete all memories for a contact."""
    try:
        from app.database.database import SessionLocal
        from app.models.models import ContactMemory

        db = SessionLocal()
        try:
            deleted = db.query(ContactMemory).filter(
                ContactMemory.contact_id == contact_id
            ).delete()
            db.commit()
            logger.info(f"Cleared {deleted} memories for contact {contact_id}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Failed to clear memories: {e}")
