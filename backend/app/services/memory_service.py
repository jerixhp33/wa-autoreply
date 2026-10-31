"""
Contact Memory & CRM Tagging Service

Extracts and stores key facts, tags, sentiment, and topics from conversations using Gemini.
Injects relevant memories into AI system prompts for personalized replies.

Runs as a fire-and-forget background task — NEVER blocks or slows customer replies.
"""
import json
import logging
import re
from typing import Optional, List
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def extract_and_store_memories(
    contact_id: str,
    user_message: str,
    ai_reply: str,
):
    """
    Use Gemini to analyze the conversation turn:
    1. Extract new facts/preferences -> ContactMemory
    2. Classify customer sentiment (positive/neutral/negative) -> Contact.sentiment
    3. Auto-assign CRM tags (Lead, Customer, Support, VIP, Friend, Tamil, etc.) -> Contact.tags
    4. Detect current topic -> Contact.last_topic
    """
    try:
        from app.database.database import SessionLocal
        from app.models.models import Contact, ContactMemory
        from app.services.gemini_service import gemini_service
        from app.config import settings
        from google.genai import types

        client = gemini_service._get_client()
        if not client:
            return

        analysis_prompt = (
            "You are a CRM intelligence and memory extraction agent for a WhatsApp auto-reply system. "
            "Analyze the conversation turn below and extract structured data.\n\n"
            "Return ONLY a valid JSON object with these exact keys:\n"
            "{\n"
            '  "memories": [{"type": "preference|fact|topic|sentiment", "key": "short_key", "value": "brief description"}],\n'
            '  "sentiment": "positive|neutral|negative",\n'
            '  "tags": ["tag1", "tag2"],\n'
            '  "topic": "Brief 2-4 word topic description"\n'
            "}\n\n"
            "Tagging guidelines:\n"
            "- 'lead': User asks about prices, products, services, offers, or availability\n"
            "- 'customer': User refers to an existing purchase, payment, or delivery\n"
            "- 'support': User asks for help, reports a bug or problem, or complains\n"
            "- 'vip': High-value, polite, repeat, or very engaged user\n"
            "- 'friend': Casual, friendly, personal chatter\n"
            "- 'tamil': User writes or speaks in Tamil or Tanglish\n"
            "- 'english': User writes or speaks in English\n"
            "- 'hindi': User writes or speaks in Hindi\n\n"
            "If no memories are noteworthy, set \"memories\": [].\n\n"
            f"USER MESSAGE: {user_message}\n"
            f"AI REPLY: {ai_reply}"
        )

        model_name = getattr(settings, "gemini_model", "gemini-2.0-flash")
        config = types.GenerateContentConfig(
            max_output_tokens=300,
            temperature=0.2,
        )

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=[types.Content(role="user", parts=[types.Part(text=analysis_prompt)])],
            config=config,
        )

        if not response or not response.text:
            return

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        if not isinstance(data, dict):
            # Fallback if list was returned
            if isinstance(data, list):
                data = {"memories": data, "sentiment": "neutral", "tags": [], "topic": None}
            else:
                return

        memories = data.get("memories", [])
        sentiment = data.get("sentiment", "neutral")
        new_tags = data.get("tags", [])
        topic = data.get("topic")

        db = SessionLocal()
        try:
            # 1. Update Contact CRM attributes (sentiment, tags, last_topic)
            contact = db.query(Contact).filter(Contact.id == contact_id).first()
            if contact:
                if sentiment in ("positive", "neutral", "negative"):
                    contact.sentiment = sentiment

                if topic and isinstance(topic, str):
                    contact.last_topic = topic[:100]

                # Merge tags
                existing_tags = set(
                    t.strip().lower() for t in (contact.tags or "").split(",") if t.strip()
                )
                if isinstance(new_tags, list):
                    for nt in new_tags:
                        if isinstance(nt, str) and nt.strip():
                            existing_tags.add(nt.strip().lower())
                contact.tags = ",".join(sorted(existing_tags))

            # 2. Upsert Contact Memories
            if isinstance(memories, list):
                for mem in memories[:5]:
                    if not isinstance(mem, dict):
                        continue
                    mem_type = mem.get("type", "fact")
                    key = mem.get("key", "").strip()
                    value = mem.get("value", "").strip()
                    if not key or not value:
                        continue

                    existing = db.query(ContactMemory).filter(
                        ContactMemory.contact_id == contact_id,
                        ContactMemory.key == key,
                    ).first()

                    if existing:
                        existing.value = value
                        existing.memory_type = mem_type
                    else:
                        new_mem = ContactMemory(
                            contact_id=contact_id,
                            memory_type=mem_type,
                            key=key,
                            value=value,
                            confidence="high",
                        )
                        db.add(new_mem)

            db.commit()
            logger.info(
                f"CRM Analysis updated for contact {contact_id}: "
                f"sentiment={sentiment}, tags={contact.tags if contact else 'none'}, topic={topic}"
            )
        except Exception as db_err:
            logger.warning(f"CRM storage error for contact {contact_id}: {db_err}")
            db.rollback()
        finally:
            db.close()

    except json.JSONDecodeError:
        logger.debug("CRM extraction returned non-JSON, skipping")
    except Exception as e:
        logger.debug(f"CRM extraction error (non-critical): {e}")


def get_memory_context(contact_id: str, db: Session) -> str:
    """
    Build a memory context string for a contact to inject into the AI prompt.
    Includes CRM profile (tags, sentiment) and stored facts.
    """
    try:
        from app.models.models import Contact, ContactMemory

        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        memories = (
            db.query(ContactMemory)
            .filter(ContactMemory.contact_id == contact_id)
            .order_by(ContactMemory.updated_at.desc().nullslast(),
                      ContactMemory.created_at.desc())
            .limit(20)
            .all()
        )

        if not contact and not memories:
            return ""

        lines = ["## 🧠 KNOWN FACTS & CRM PROFILE (from previous conversations)"]

        if contact:
            if contact.tags:
                lines.append(f"- Contact Tags: {contact.tags}")
            if contact.sentiment and contact.sentiment != "neutral":
                lines.append(f"- Customer Sentiment: {contact.sentiment}")
            if contact.last_topic:
                lines.append(f"- Last Discussed Topic: {contact.last_topic}")

        for mem in memories:
            lines.append(f"- {mem.key}: {mem.value}")

        lines.append(
            "\nUse these facts to personalize your reply naturally. "
            "Never quote these tags directly to the user."
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
