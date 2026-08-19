'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import {
  Bot, User, Clock, CheckCheck, Send, Loader2,
  UserCheck, BotOff, Search, MessageSquare, Sparkles
} from 'lucide-react';
import { conversationsApi, messagesApi, whatsappApi } from '@/lib/api';
import { Conversation, Message, WhatsAppAccount } from '@/types';
import { formatRelativeTime, formatTime, getInitials, cn, truncate } from '@/lib/utils';
import { useWebSocket } from '@/hooks/useWebSocket';
import { toast } from 'sonner';

function MessageBubble({ message }: { message: Message }) {
  const isOutgoing = message.direction === 'outgoing';

  return (
    <div className={cn('flex', isOutgoing ? 'justify-end' : 'justify-start')}>
      <div className="max-w-sm">
        <div
          className={cn(
            'rounded-2xl px-4 py-2.5 text-sm',
            isOutgoing && message.ai_generated
              ? 'bg-whatsapp/15 border border-whatsapp/25 rounded-tr-sm'
              : isOutgoing
              ? 'bg-primary text-primary-foreground rounded-tr-sm'
              : 'bg-card border border-border rounded-tl-sm'
          )}
        >
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
        <div className={cn(
          'flex items-center gap-1.5 mt-1 px-1',
          isOutgoing ? 'justify-end' : 'justify-start'
        )}>
          {message.ai_generated && (
            <span className="flex items-center gap-1 text-[10px] text-whatsapp font-medium">
              <Sparkles className="h-2.5 w-2.5" /> AI
            </span>
          )}
          <span className="text-[10px] text-muted-foreground">{formatTime(message.created_at)}</span>
          {isOutgoing && (
            <CheckCheck className="h-3 w-3 text-muted-foreground" />
          )}
        </div>
      </div>
    </div>
  );
}

function ConversationItem({
  conv,
  selected,
  onClick,
}: {
  conv: Conversation;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent',
        selected ? 'bg-accent' : ''
      )}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold">
        {getInitials(conv.contact?.name || conv.contact?.phone_number)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium truncate">
            {conv.contact?.name || conv.contact?.phone_number}
          </p>
          <span className="text-[10px] text-muted-foreground shrink-0 ml-2">
            {formatRelativeTime(conv.last_message_at)}
          </span>
        </div>
        <div className="flex items-center justify-between mt-0.5">
          <p className="text-xs text-muted-foreground truncate flex-1">
            {conv.last_message ? truncate(conv.last_message, 36) : 'No messages yet'}
          </p>
          <div className="flex items-center gap-1 ml-2 shrink-0">
            {conv.human_takeover ? (
              <span className="rounded-full bg-blue-500/10 text-blue-500 px-1.5 py-0.5 text-[10px] font-medium">Human</span>
            ) : conv.ai_enabled ? (
              <span className="rounded-full bg-whatsapp/10 text-whatsapp px-1.5 py-0.5 text-[10px] font-medium">AI</span>
            ) : null}
          </div>
        </div>
      </div>
    </button>
  );
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConv, setSelectedConv] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [msgLoading, setMsgLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [messageInput, setMessageInput] = useState('');
  const [search, setSearch] = useState('');
  const [aiTyping, setAiTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { on } = useWebSocket();

  const loadConversations = useCallback(async () => {
    try {
      const res = await conversationsApi.list();
      setConversations(res.data);
    } catch (err) {
      console.error('Failed to load conversations', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMessages = useCallback(async (convId: string) => {
    setMsgLoading(true);
    try {
      const res = await conversationsApi.getMessages(convId, 100);
      setMessages(res.data);
    } catch (err) {
      console.error('Failed to load messages', err);
    } finally {
      setMsgLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
    whatsappApi.listAccounts().then(res => setAccounts(res.data)).catch(console.error);
  }, [loadConversations]);

  useEffect(() => {
    if (selectedConv) {
      loadMessages(selectedConv.id);
    }
  }, [selectedConv, loadMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // WebSocket events
  useEffect(() => {
    // Helper: add a message only if its id isn't already in the list
    const addMessageIfNew = (newMsg: Message) => {
      setMessages(prev => {
        if (prev.some(m => m.id === newMsg.id)) return prev;
        return [...prev, newMsg];
      });
    };

    const unsub1 = on('message_received', (data: any) => {
      if (selectedConv && data.conversation_id === selectedConv.id) {
        addMessageIfNew({
          id: data.id,
          conversation_id: data.conversation_id,
          direction: 'incoming',
          content: data.content,
          ai_generated: false,
          status: 'delivered',
          message_type: 'text',
          whatsapp_message_id: null,
          created_at: data.created_at,
        });
      }
      loadConversations();
    });

    const unsub2 = on('ai_reply_started', (data: any) => {
      if (selectedConv && data.conversation_id === selectedConv.id) {
        setAiTyping(true);
      }
    });

    const unsub3 = on('ai_reply_completed', (data: any) => {
      setAiTyping(false);
      if (selectedConv && data.conversation_id === selectedConv.id) {
        addMessageIfNew({
          id: data.id,
          conversation_id: data.conversation_id,
          direction: 'outgoing',
          content: data.content,
          ai_generated: true,
          status: 'sent',
          message_type: 'text',
          whatsapp_message_id: null,
          created_at: data.created_at,
        });
      }
      loadConversations();
    });

    const unsub4 = on('message_sent', (data: any) => {
      if (selectedConv && data.conversation_id === selectedConv.id) {
        addMessageIfNew({
          id: data.id,
          conversation_id: data.conversation_id,
          direction: 'outgoing',
          content: data.content,
          ai_generated: false,
          status: 'sent',
          message_type: 'text',
          whatsapp_message_id: null,
          created_at: data.created_at,
        });
      }
      loadConversations();
    });

    return () => { unsub1(); unsub2(); unsub3(); unsub4(); };
  }, [on, selectedConv, loadConversations]);

  const handleSend = async () => {
    if (!messageInput.trim() || !selectedConv) return;
    const content = messageInput.trim();
    setMessageInput('');
    setSending(true);
    try {
      const account = accounts.find(a => a.id === selectedConv.whatsapp_account_id);
      if (!account) throw new Error('Account not found');
      const phone = selectedConv.contact?.phone_number;
      if (!phone) throw new Error('No phone number');
      await messagesApi.send(account.id, phone, content);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to send message');
      setMessageInput(content);
    } finally {
      setSending(false);
    }
  };

  const toggleTakeover = async () => {
    if (!selectedConv) return;
    const newVal = !selectedConv.human_takeover;
    try {
      await conversationsApi.update(selectedConv.id, { human_takeover: newVal });
      setSelectedConv(prev => prev ? { ...prev, human_takeover: newVal } : null);
      toast.success(newVal ? 'Human takeover enabled' : 'Returned to AI');
    } catch {
      toast.error('Failed to update conversation');
    }
  };

  const filteredConvs = conversations.filter(c => {
    const name = c.contact?.name || c.contact?.phone_number || '';
    return name.toLowerCase().includes(search.toLowerCase());
  });

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <div className="flex flex-col w-80 border-r border-border bg-card">
        <div className="p-4 border-b border-border">
          <h2 className="font-semibold mb-3">Conversations</h2>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full rounded-lg border border-input bg-background pl-8 pr-3 py-2 text-sm outline-none focus:border-primary"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredConvs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-4">
              <MessageSquare className="h-10 w-10 text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">No conversations yet</p>
            </div>
          ) : (
            filteredConvs.map(conv => (
              <ConversationItem
                key={conv.id}
                conv={conv}
                selected={selectedConv?.id === conv.id}
                onClick={() => setSelectedConv(conv)}
              />
            ))
          )}
        </div>
      </div>

      {/* Chat area */}
      {!selectedConv ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center">
            <MessageSquare className="h-12 w-12 text-muted-foreground mx-auto mb-3" />
            <p className="text-muted-foreground">Select a conversation to start</p>
          </div>
        </div>
      ) : (
        <div className="flex flex-1 flex-col min-w-0">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-border px-6 py-4 bg-card">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-sm font-semibold">
              {getInitials(selectedConv.contact?.name || selectedConv.contact?.phone_number)}
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-semibold truncate">
                {selectedConv.contact?.name || selectedConv.contact?.phone_number}
              </p>
              <p className="text-xs text-muted-foreground">
                {selectedConv.contact?.phone_number}
              </p>
            </div>
            <button
              onClick={toggleTakeover}
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                selectedConv.human_takeover
                  ? 'bg-blue-500/10 text-blue-500 hover:bg-blue-500/20'
                  : 'bg-whatsapp/10 text-whatsapp hover:bg-whatsapp/20'
              )}
            >
              {selectedConv.human_takeover ? (
                <><UserCheck className="h-3.5 w-3.5" /> Human Active</>
              ) : (
                <><Bot className="h-3.5 w-3.5" /> AI Active</>
              )}
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-6 space-y-3">
            {msgLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                No messages yet
              </div>
            ) : (
              messages.map(msg => <MessageBubble key={msg.id} message={msg} />)
            )}

            {aiTyping && (
              <div className="flex justify-end">
                <div className="bg-whatsapp/10 border border-whatsapp/20 rounded-2xl rounded-tr-sm px-4 py-3">
                  <div className="flex gap-1 items-center">
                    <Sparkles className="h-3.5 w-3.5 text-whatsapp" />
                    <span className="text-xs text-whatsapp">AI is typing</span>
                    <div className="flex gap-0.5 ml-1">
                      {[0,1,2].map(i => (
                        <div key={i} className="h-1.5 w-1.5 rounded-full bg-whatsapp animate-bounce" style={{animationDelay: `${i * 0.15}s`}} />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="border-t border-border p-4 bg-card">
            <div className="flex items-end gap-3">
              <textarea
                value={messageInput}
                onChange={e => setMessageInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Type a message..."
                rows={1}
                className="flex-1 resize-none rounded-xl border border-input bg-background px-4 py-3 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary max-h-32"
              />
              <button
                onClick={handleSend}
                disabled={sending || !messageInput.trim()}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-whatsapp text-white hover:bg-whatsapp-dark transition-colors disabled:opacity-50"
              >
                {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </button>
            </div>
            {selectedConv.human_takeover && (
              <p className="text-xs text-blue-500 mt-2 flex items-center gap-1">
                <UserCheck className="h-3 w-3" /> Human takeover active — AI replies paused
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
