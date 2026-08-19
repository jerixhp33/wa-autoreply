from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime


# ─── Auth ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ─── WhatsApp Accounts ────────────────────────────────────────────────────────

class WhatsAppAccountCreate(BaseModel):
    name: str


class WhatsAppAccountResponse(BaseModel):
    id: str
    user_id: str
    name: str
    phone_number: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QRResponse(BaseModel):
    qr_code: Optional[str] = None
    status: str


# ─── Contacts ─────────────────────────────────────────────────────────────────

class ContactResponse(BaseModel):
    id: str
    whatsapp_account_id: str
    phone_number: str
    name: Optional[str] = None
    ai_enabled: bool
    blocked: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Conversations ────────────────────────────────────────────────────────────

class ConversationResponse(BaseModel):
    id: str
    whatsapp_account_id: str
    contact_id: str
    ai_enabled: bool
    human_takeover: bool
    last_message_at: Optional[datetime] = None
    created_at: datetime
    contact: Optional[ContactResponse] = None
    last_message: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationUpdate(BaseModel):
    ai_enabled: Optional[bool] = None
    human_takeover: Optional[bool] = None


# ─── Messages ─────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    whatsapp_message_id: Optional[str] = None
    direction: str
    message_type: str
    content: str
    ai_generated: bool
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    account_id: str
    phone: str
    message: str


# ─── Bot Settings ─────────────────────────────────────────────────────────────

class BotSettingsResponse(BaseModel):
    id: str
    whatsapp_account_id: str
    enabled: bool
    system_prompt: str
    language: str
    max_reply_length: int
    respond_to_groups: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BotSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    system_prompt: Optional[str] = None
    language: Optional[str] = None
    max_reply_length: Optional[int] = None
    respond_to_groups: Optional[bool] = None


# ─── API Keys ─────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    status: str
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApiKeyCreatedResponse(BaseModel):
    id: str
    name: str
    prefix: str
    key: str  # Only shown once
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Public API ───────────────────────────────────────────────────────────────

class PublicSendMessageRequest(BaseModel):
    account_id: str
    phone: str
    message: str


# ─── Dashboard Stats ──────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    connected_accounts: int
    messages_today: int
    ai_replies_today: int
    active_conversations: int
