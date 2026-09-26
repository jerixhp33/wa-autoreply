from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Enum, LargeBinary
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum
import uuid


Base = declarative_base()


def gen_uuid():
    return str(uuid.uuid4())


class AccountStatus(str, enum.Enum):
    disconnected = "disconnected"
    connecting = "connecting"
    connected = "connected"
    error = "error"


class MessageDirection(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"


class MessageStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class ApiKeyStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    whatsapp_accounts = relationship("WhatsAppAccount", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")


class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    session_path = Column(String, nullable=True)
    status = Column(String, default=AccountStatus.disconnected)
    qr_code = Column(Text, nullable=True)
    session_data = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="whatsapp_accounts")
    contacts = relationship("Contact", back_populates="whatsapp_account", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="whatsapp_account", cascade="all, delete-orphan")
    bot_settings = relationship("BotSettings", back_populates="whatsapp_account", cascade="all, delete-orphan", uselist=False)
    documents = relationship("Document", back_populates="whatsapp_account", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=gen_uuid)
    whatsapp_account_id = Column(String, ForeignKey("whatsapp_accounts.id"), nullable=False)
    phone_number = Column(String, nullable=False)
    name = Column(String, nullable=True)
    ai_enabled = Column(Boolean, default=True)
    blocked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    whatsapp_account = relationship("WhatsAppAccount", back_populates="contacts")
    conversations = relationship("Conversation", back_populates="contact", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=gen_uuid)
    whatsapp_account_id = Column(String, ForeignKey("whatsapp_accounts.id"), nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False)
    ai_enabled = Column(Boolean, default=True)
    human_takeover = Column(Boolean, default=False)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    whatsapp_account = relationship("WhatsAppAccount", back_populates="conversations")
    contact = relationship("Contact", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_uuid)
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    whatsapp_message_id = Column(String, nullable=True)
    direction = Column(String, nullable=False)
    message_type = Column(String, default="text")
    content = Column(Text, nullable=True)
    media_path = Column(String, nullable=True)
    media_mime_type = Column(String, nullable=True)
    media_caption = Column(Text, nullable=True)
    transcription = Column(Text, nullable=True)
    ai_generated = Column(Boolean, default=False)
    status = Column(String, default=MessageStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id = Column(String, primary_key=True, default=gen_uuid)
    whatsapp_account_id = Column(String, ForeignKey("whatsapp_accounts.id"), unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    system_prompt = Column(Text, default="""You are a friendly WhatsApp customer support assistant.

Keep replies short and natural.

Answer only using information provided by the business.

Never invent prices, products, order information, delivery information, or policies.

If you do not know something, politely ask the customer to contact human support.

Reply in the same language as the customer when possible.

Make the response suitable for WhatsApp.""")
    language = Column(String, default="automatic")
    max_reply_length = Column(Integer, default=500)
    respond_to_groups = Column(Boolean, default=False)
    voice_reply_enabled = Column(Boolean, default=False)
    voice_name = Column(String, default="en-IN-NeerjaNeural")
    voice_reply_mode = Column(String, default="audio_only")  # 'audio_only' or 'always'
    groq_api_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    whatsapp_account = relationship("WhatsAppAccount", back_populates="bot_settings")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)
    prefix = Column(String, nullable=False)
    status = Column(String, default=ApiKeyStatus.active)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=gen_uuid)
    whatsapp_account_id = Column(String, ForeignKey("whatsapp_accounts.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # 'pdf', 'txt'
    file_size = Column(Integer, default=0)
    extracted_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    whatsapp_account = relationship("WhatsAppAccount", back_populates="documents")

