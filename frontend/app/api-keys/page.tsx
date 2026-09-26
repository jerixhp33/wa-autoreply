'use client';

import { useEffect, useState } from 'react';
import {
  Key, Plus, Trash2, Copy, Check, Eye, EyeOff,
  Loader2, AlertTriangle, Clock
} from 'lucide-react';
import { apiKeysApi, whatsappApi } from '@/lib/api';
import { ApiKey, ApiKeyCreated } from '@/types';
import { formatDate, formatRelativeTime } from '@/lib/utils';
import { toast } from 'sonner';

function CreatedKeyBanner({ apiKey, onDismiss }: { apiKey: ApiKeyCreated; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(apiKey.key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border border-whatsapp/30 bg-whatsapp/5 p-5 mb-6">
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-whatsapp/20">
          <Key className="h-4 w-4 text-whatsapp" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm text-whatsapp">API Key Created</p>
          <p className="text-xs text-muted-foreground mt-0.5 mb-3">
            Copy this key now — it will never be shown again.
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1 rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs">
              {visible ? apiKey.key : '•'.repeat(apiKey.key.length)}
            </div>
            <button
              onClick={() => setVisible(!visible)}
              className="rounded-lg border border-border p-2 hover:bg-accent transition-colors"
              title={visible ? 'Hide' : 'Show'}
            >
              {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
            <button
              onClick={copy}
              className="rounded-lg border border-border p-2 hover:bg-accent transition-colors"
              title="Copy"
            >
              {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="text-muted-foreground hover:text-foreground text-xs"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyCreated | null>(null);
  const [accountAccountId, setAccountAccountId] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await apiKeysApi.list();
      setKeys(res.data);
      const accsRes = await whatsappApi.listAccounts();
      if (accsRes.data && accsRes.data.length > 0) {
        setAccountAccountId(accsRes.data[0].id);
      }
    } catch (err) {
      console.error('Failed to load API keys', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await apiKeysApi.create(newName.trim());
      setNewKey(res.data);
      setNewName('');
      setShowForm(false);
      await load();
      toast.success('API key created');
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to create API key');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (id: string, name: string) => {
    if (!confirm(`Revoke API key "${name}"? Any apps using it will stop working.`)) return;
    try {
      await apiKeysApi.revoke(id);
      setKeys(prev => prev.filter(k => k.id !== id));
      toast.success('API key revoked');
    } catch {
      toast.error('Failed to revoke key');
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="text-muted-foreground mt-1">
            Use these keys to integrate WhatsApp messaging into your own apps
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2.5 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create API Key
        </button>
      </div>

      {/* Newly created key banner */}
      {newKey && (
        <CreatedKeyBanner
          apiKey={newKey}
          onDismiss={() => setNewKey(null)}
        />
      )}

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="rounded-xl border border-border bg-card p-5 mb-6">
          <h3 className="font-semibold mb-4">New API Key</h3>
          <div className="flex gap-3">
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Key name (e.g. My App, Production)"
              className="flex-1 rounded-lg border border-input bg-background px-4 py-2.5 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            />
            <button
              type="submit"
              disabled={creating || !newName.trim()}
              className="rounded-lg bg-whatsapp px-4 py-2.5 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors disabled:opacity-50"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Create'}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-border px-4 py-2.5 text-sm font-medium hover:bg-accent transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* API Usage docs */}
      <div className="rounded-xl border border-border bg-card p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">How to use</h3>
          <a href="/whatsapp" className="text-xs text-whatsapp hover:underline font-medium flex items-center gap-1">
            Find Account ID →
          </a>
        </div>
        <div className="space-y-3 font-mono text-xs bg-muted rounded-lg p-4">
          <p className="text-muted-foreground"># Send a message via API</p>
          <p>curl -X POST https://wa-autoreply-a416.onrender.com/api/v1/messages/send \</p>
          <p className="pl-4">-H "Authorization: Bearer {newKey?.key || 'wha_live_xxx...'}" \</p>
          <p className="pl-4">-H "Content-Type: application/json" \</p>
          <p className="pl-4">-d {'\'{"account_id": "' + (accountAccountId || 'YOUR_ACCOUNT_ID') + '", "phone": "919360490974", "message": "Hello!"}\''}</p>
        </div>
        <div className="mt-3 text-xs text-muted-foreground bg-muted/40 p-3 rounded-lg border border-border/50 flex items-center justify-between">
          <span>💡 <strong>Need your Account ID?</strong> Go to <a href="/whatsapp" className="text-whatsapp font-medium hover:underline">WhatsApp Accounts</a> — each account card has a 1-click <strong>Copy ID</strong> button.</span>
        </div>
      </div>

      {/* Keys list */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : keys.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center rounded-xl border border-dashed border-border">
          <Key className="h-12 w-12 text-muted-foreground mb-4" />
          <p className="font-medium">No API keys</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Create your first API key to integrate with your applications
          </p>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
          >
            <Plus className="h-4 w-4" /> Create API Key
          </button>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border bg-muted/50">
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-4 text-xs font-medium text-muted-foreground uppercase tracking-wide">
              <span>Name</span>
              <span>Prefix</span>
              <span>Last used</span>
              <span></span>
            </div>
          </div>
          <div className="divide-y divide-border">
            {keys.map((key) => (
              <div key={key.id} className="grid grid-cols-[1fr_auto_auto_auto] gap-4 items-center px-5 py-4">
                <div>
                  <p className="text-sm font-medium">{key.name}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Created {formatDate(key.created_at)}
                  </p>
                </div>
                <span className="font-mono text-xs bg-muted rounded-md px-2 py-1 text-muted-foreground">
                  {key.prefix}...
                </span>
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {key.last_used_at ? formatRelativeTime(key.last_used_at) : 'Never'}
                </span>
                <button
                  onClick={() => handleRevoke(key.id, key.name)}
                  className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Revoke
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Security notice */}
      <div className="flex items-start gap-3 rounded-xl border border-yellow-500/20 bg-yellow-500/5 p-4 mt-6">
        <AlertTriangle className="h-4 w-4 text-yellow-500 shrink-0 mt-0.5" />
        <div className="text-sm">
          <p className="font-medium text-yellow-500">Keep your API keys secret</p>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Never expose them in client-side code or public repositories.
            If a key is compromised, revoke it immediately and create a new one.
          </p>
        </div>
      </div>
    </div>
  );
}
