'use client';

import { useEffect, useState } from 'react';
import { Bot, Save, Loader2, Settings2, Sun, Moon } from 'lucide-react';
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
  });

  useEffect(() => {
    const load = async () => {
      try {
        const res = await whatsappApi.listAccounts();
        setAccounts(res.data);
        if (res.data.length > 0) {
          setSelectedId(res.data[0].id);
        }
      } catch (err) {
        console.error('Failed to load accounts', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

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
      toast.error(err.response?.data?.detail || 'Failed to save settings');
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
      {accounts.length === 0 ? (
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
