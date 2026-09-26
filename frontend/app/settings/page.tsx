'use client';

import { useEffect, useState, useCallback } from 'react';
import { Bot, Save, Loader2, Settings2, Sun, Moon, Mic } from 'lucide-react';
import { whatsappApi, botApi } from '@/lib/api';
import { WhatsAppAccount, BotSettings } from '@/types';
import { toast } from 'sonner';
import { useTheme } from 'next-themes';

const DEFAULT_PROMPT = `You are a friendly WhatsApp customer support assistant.

Keep replies short and natural.

Answer only using information provided by the business.

Never invent prices, products, order information, delivery information, or policies.

If you do not know something, politely ask the customer to contact human support.

Reply in the same language as the customer when possible.

Make the response suitable for WhatsApp.`;

export default function SettingsPage() {
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { theme, setTheme } = useTheme();

  const [form, setForm] = useState({
    enabled: true,
    system_prompt: DEFAULT_PROMPT,
    language: 'automatic',
    max_reply_length: 500,
    respond_to_groups: false,
    voice_reply_enabled: false,
    voice_name: 'en-IN-NeerjaNeural',
    voice_reply_mode: 'audio_only',
  });

  const [loadError, setLoadError] = useState<string | null>(null);

  const loadAccounts = useCallback(async () => {
    try {
      setLoadError(null);
      const res = await whatsappApi.listAccounts();
      setAccounts(res.data);
      if (res.data.length > 0) {
        setSelectedId(res.data[0].id);
      }
    } catch (err) {
      console.error('Failed to load accounts', err);
      setLoadError('Failed to load accounts. Please check your connection.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    if (!selectedId) return;
    const load = async () => {
      try {
        const res = await botApi.getSettings(selectedId);
        setSettings(res.data);
        setForm({
          enabled: res.data.enabled,
          system_prompt: res.data.system_prompt,
          language: res.data.language,
          max_reply_length: res.data.max_reply_length,
          respond_to_groups: res.data.respond_to_groups,
          voice_reply_enabled: res.data.voice_reply_enabled ?? false,
          voice_name: res.data.voice_name ?? 'en-IN-NeerjaNeural',
          voice_reply_mode: res.data.voice_reply_mode ?? 'audio_only',
        });
      } catch (err) {
        console.error('Failed to load settings', err);
      }
    };
    load();
  }, [selectedId]);

  const handleSave = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      await botApi.updateSettings(selectedId, form);
      toast.success('Settings saved');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : 'Failed to save settings';
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-2xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-1">Configure your AI bot behavior</p>
      </div>

      {/* Appearance */}
      <div className="rounded-xl border border-border bg-card p-6 mb-6">
        <h2 className="font-semibold mb-4 flex items-center gap-2">
          <Settings2 className="h-4 w-4" /> Appearance
        </h2>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Theme</p>
            <p className="text-xs text-muted-foreground">Switch between light and dark mode</p>
          </div>
          <div className="flex rounded-lg border border-border overflow-hidden">
            {['light', 'dark'].map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors
                  ${theme === t ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'}`}
              >
                {t === 'light' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Account selector */}
      {loadError ? (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
          <p className="text-sm font-semibold text-red-500">{loadError}</p>
          <button
            onClick={loadAccounts}
            className="mt-3 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-500 px-4 py-1.5 text-xs font-medium transition-colors"
          >
            Retry
          </button>
        </div>
      ) : accounts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <Bot className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No WhatsApp accounts found. Add one first.
          </p>
        </div>
      ) : (
        <>
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2">WhatsApp Account</label>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              className="w-full rounded-lg border border-input bg-background px-4 py-2.5 text-sm outline-none focus:border-primary"
            >
              {accounts.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <div className="rounded-xl border border-border bg-card p-6 space-y-6">
            <h2 className="font-semibold flex items-center gap-2">
              <Bot className="h-4 w-4" /> AI Auto Reply
            </h2>

            {/* Enable toggle */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">AI Auto Reply</p>
                <p className="text-xs text-muted-foreground">Automatically reply to incoming messages</p>
              </div>
              <button
                onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
                className={`relative h-6 w-11 rounded-full transition-colors ${form.enabled ? 'bg-whatsapp' : 'bg-muted'}`}
              >
                <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* Language */}
            <div>
              <label className="block text-sm font-medium mb-2">AI Language</label>
              <select
                value={form.language}
                onChange={(e) => setForm(f => ({ ...f, language: e.target.value }))}
                className="w-full rounded-lg border border-input bg-background px-4 py-2.5 text-sm outline-none focus:border-primary"
              >
                <option value="automatic">Automatic (match customer)</option>
                <option value="english">English</option>
                <option value="tamil">Tamil</option>
                <option value="tanglish">Tanglish</option>
                <option value="hindi">Hindi</option>
                <option value="spanish">Spanish</option>
                <option value="french">French</option>
              </select>
            </div>

            {/* Max reply length */}
            <div>
              <label className="block text-sm font-medium mb-2">
                Maximum Reply Length: <span className="text-muted-foreground">{form.max_reply_length} chars</span>
              </label>
              <input
                type="range"
                min={100}
                max={2000}
                step={50}
                value={form.max_reply_length}
                onChange={(e) => setForm(f => ({ ...f, max_reply_length: parseInt(e.target.value) }))}
                className="w-full accent-whatsapp"
              />
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>Short (100)</span>
                <span>Long (2000)</span>
              </div>
            </div>

            {/* Respond to groups */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Respond to Groups</p>
                <p className="text-xs text-muted-foreground">Reply in group chats (off by default)</p>
              </div>
              <button
                onClick={() => setForm(f => ({ ...f, respond_to_groups: !f.respond_to_groups }))}
                className={`relative h-6 w-11 rounded-full transition-colors ${form.respond_to_groups ? 'bg-whatsapp' : 'bg-muted'}`}
              >
                <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.respond_to_groups ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* AI Voice Note Replies (TTS) */}
            <div className="rounded-xl border border-border/80 bg-muted/20 p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold flex items-center gap-2">
                    <Mic className="h-4 w-4 text-whatsapp" /> AI Voice Note Replies (TTS)
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Reply to customers with high-quality natural voice notes on WhatsApp
                  </p>
                </div>
                <button
                  onClick={() => setForm(f => ({ ...f, voice_reply_enabled: !f.voice_reply_enabled }))}
                  className={`relative h-6 w-11 rounded-full transition-colors ${form.voice_reply_enabled ? 'bg-whatsapp' : 'bg-muted'}`}
                >
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.voice_reply_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
                </button>
              </div>

              {form.voice_reply_enabled && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-border/50">
                  {/* Voice Accent Selector */}
                  <div>
                    <label className="block text-xs font-medium mb-1.5">Voice Accent & Persona</label>
                    <select
                      value={form.voice_name}
                      onChange={(e) => setForm(f => ({ ...f, voice_name: e.target.value }))}
                      className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none focus:border-whatsapp"
                    >
                      <option value="en-IN-NeerjaNeural">🇮🇳 Indian English (Female - Neerja)</option>
                      <option value="en-IN-PrabhatNeural">🇮🇳 Indian English (Male - Prabhat)</option>
                      <option value="en-US-JennyNeural">🇺🇸 US English (Female - Jenny)</option>
                      <option value="en-US-GuyNeural">🇺🇸 US English (Male - Guy)</option>
                      <option value="ta-IN-PallaviNeural">🇮🇳 Tamil (Female - Pallavi)</option>
                      <option value="ta-IN-ValluvarNeural">🇮🇳 Tamil (Male - Valluvar)</option>
                      <option value="hi-IN-SwaraNeural">🇮🇳 Hindi (Female - Swara)</option>
                      <option value="hi-IN-MadhurNeural">🇮🇳 Hindi (Male - Madhur)</option>
                    </select>
                  </div>

                  {/* Voice Trigger Mode */}
                  <div>
                    <label className="block text-xs font-medium mb-1.5">When to send voice notes</label>
                    <select
                      value={form.voice_reply_mode}
                      onChange={(e) => setForm(f => ({ ...f, voice_reply_mode: e.target.value as any }))}
                      className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none focus:border-whatsapp"
                    >
                      <option value="audio_only">Only when customer sends a voice note</option>
                      <option value="always">Always reply with voice note</option>
                    </select>
                  </div>
                </div>
              )}
            </div>

            {/* System prompt */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium">System Prompt</label>
                <button
                  onClick={() => setForm(f => ({ ...f, system_prompt: DEFAULT_PROMPT }))}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Reset to default
                </button>
              </div>
              <textarea
                value={form.system_prompt}
                onChange={(e) => setForm(f => ({ ...f, system_prompt: e.target.value }))}
                rows={10}
                className="w-full rounded-lg border border-input bg-background px-4 py-3 text-sm outline-none focus:border-primary font-mono resize-y"
              />
              <p className="text-xs text-muted-foreground mt-1">
                This is the AI's personality and behavior instructions.
              </p>
            </div>

            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-whatsapp px-5 py-2.5 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save Settings
            </button>
          </div>
        </>
      )}
    </div>
  );
}
