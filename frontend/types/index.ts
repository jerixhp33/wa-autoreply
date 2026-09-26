export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface WhatsAppAccount {
  id: string;
  user_id: string;
  name: string;
  phone_number: string | null;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  created_at: string;
  updated_at: string | null;
}

export interface Contact {
  id: string;
  whatsapp_account_id: string;
  phone_number: string;
  name: string | null;
  ai_enabled: boolean;
  blocked: boolean;
  created_at: string;
}

export interface Conversation {
  id: string;
  whatsapp_account_id: string;
  contact_id: string;
  ai_enabled: boolean;
  human_takeover: boolean;
  last_message_at: string | null;
  created_at: string;
  contact: Contact | null;
  last_message: string | null;
  last_message_direction: 'incoming' | 'outgoing' | null;
  unread_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  whatsapp_message_id: string | null;
  direction: 'incoming' | 'outgoing';
  message_type: string;
  content: string;
  ai_generated: boolean;
  status: 'pending' | 'sent' | 'delivered' | 'read' | 'failed';
  created_at: string;
}

export interface BotSettings {
  id: string;
  whatsapp_account_id: string;
  enabled: boolean;
  system_prompt: string;
  language: string;
  max_reply_length: number;
  respond_to_groups: boolean;
  voice_reply_enabled: boolean;
  voice_name: string;
  voice_reply_mode: 'audio_only' | 'always';
  created_at: string;
  updated_at: string | null;
}

export interface Document {
  id: string;
  whatsapp_account_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  is_active: boolean;
  created_at: string;
  extracted_text_preview?: string;
}

export interface DocumentDetail extends Document {
  extracted_text: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface DashboardStats {
  connected_accounts: number;
  messages_today: number;
  ai_replies_today: number;
  active_conversations: number;
}

export interface WSEvent {
  event: string;
  data: Record<string, unknown>;
}

export type WSEventType =
  | 'qr_updated'
  | 'account_connected'
  | 'account_disconnected'
  | 'message_received'
  | 'message_sent'
  | 'ai_reply_started'
  | 'ai_reply_completed'
  | 'ai_reply_error';
