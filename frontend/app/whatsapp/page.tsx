'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  Plus, Smartphone, RefreshCw, Trash2, Unplug, QrCode, CheckCircle2,
  AlertCircle, Loader2, X, Link2, Copy
} from 'lucide-react';
import { whatsappApi } from '@/lib/api';
import { WhatsAppAccount } from '@/types';
import { getStatusDot, formatRelativeTime } from '@/lib/utils';
import { useWebSocket } from '@/hooks/useWebSocket';
import { toast } from 'sonner';
import Image from 'next/image';

function QRModal({
  account,
  onClose
}: {
  account: WhatsAppAccount;
  onClose: () => void;
}) {
  const [qrData, setQrData] = useState<string | null>(null);
  const [status, setStatus] = useState(account.status);
  const { on } = useWebSocket();

  useEffect(() => {
    // Poll for QR
    const loadQR = async () => {
      try {
        const res = await whatsappApi.getQR(account.id);
        setQrData(res.data.qr_code);
        setStatus(res.data.status);
        if (res.data.status === 'connected') {
          toast.success('WhatsApp connected successfully!');
          setTimeout(onClose, 1200);
        }
      } catch (err) {
        console.error('Failed to load QR', err);
      }
    };

    loadQR();
    const interval = setInterval(loadQR, 3000);
    return () => clearInterval(interval);
  }, [account.id, onClose]);

  useEffect(() => {
    const unsub1 = on('qr_updated', (data: any) => {
      if (data.account_id === account.id) {
        setQrData(data.qr_code);
        setStatus('connecting');
      }
    });
    const unsub2 = on('account_connected', (data: any) => {
      if (data.account_id === account.id) {
        setStatus('connected');
        toast.success('WhatsApp connected successfully!');
        setTimeout(onClose, 2000);
      }
    });
    return () => { unsub1(); unsub2(); };
  }, [on, account.id, onClose]);

  const isConnected = status === 'connected';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-sm rounded-2xl border border-border bg-card shadow-2xl">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-md p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="p-8 text-center">
          <h2 className="text-lg font-semibold mb-1">Connect WhatsApp</h2>
          <p className="text-sm text-muted-foreground mb-6">
            {account.name}
          </p>

          {isConnected ? (
            <div className="flex flex-col items-center gap-3 py-8">
              <CheckCircle2 className="h-16 w-16 text-green-500" />
              <p className="font-semibold text-green-500">WhatsApp Connected!</p>
            </div>
          ) : qrData ? (
            <>
              <div className="rounded-xl border-2 border-border p-3 inline-block bg-white mb-6">
                {qrData.startsWith('data:image') ? (
                  <img src={qrData} alt="QR Code" className="h-52 w-52" />
                ) : (
                  <div className="h-52 w-52 flex items-center justify-center">
                    <QrCode className="h-32 w-32 text-black" />
                  </div>
                )}
              </div>
              <div className="text-left text-sm space-y-2 text-muted-foreground bg-muted rounded-lg p-4">
                <p className="font-medium text-foreground">To connect:</p>
                <ol className="list-decimal list-inside space-y-1">
                  <li>Open WhatsApp on your phone</li>
                  <li>Tap <strong>Linked Devices</strong></li>
                  <li>Tap <strong>Link a Device</strong></li>
                  <li>Scan this QR code</li>
                </ol>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Generating QR code...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AccountCard({
  account,
  onRefresh,
}: {
  account: WhatsAppAccount;
  onRefresh: () => void;
}) {
  const [showQR, setShowQR] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      await whatsappApi.disconnect(account.id);
      toast.success('Account disconnected');
      onRefresh();
    } catch {
      toast.error('Failed to disconnect');
    } finally {
      setLoading(false);
    }
  };

  const handleReconnect = async () => {
    setLoading(true);
    try {
      await whatsappApi.reconnect(account.id);
      toast.success('Reconnecting...');
      setShowQR(true);
      onRefresh();
    } catch {
      toast.error('Failed to reconnect');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Delete "${account.name}"? This cannot be undone.`)) return;
    setLoading(true);
    try {
      await whatsappApi.deleteAccount(account.id);
      toast.success('Account deleted');
      onRefresh();
    } catch {
      toast.error('Failed to delete account');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-start gap-4">
          <div className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-whatsapp/10">
            <Smartphone className="h-6 w-6 text-whatsapp" />
            <span className={`absolute -right-0.5 -top-0.5 h-3.5 w-3.5 rounded-full border-2 border-card ${getStatusDot(account.status)}`} />
          </div>

          <div className="flex-1 min-w-0">
            <p className="font-semibold">{account.name}</p>
            <p className="text-sm text-muted-foreground mt-0.5">
              {account.phone_number ? `+${account.phone_number}` : 'Not connected'}
            </p>
            <div className="flex items-center gap-1.5 mt-1.5">
              <span className="font-mono text-[11px] text-muted-foreground bg-muted/80 px-2 py-0.5 rounded border border-border/50 select-all">
                ID: {account.id}
              </span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(account.id);
                  toast.success('Account ID copied to clipboard!');
                }}
                className="p-1 text-muted-foreground hover:text-foreground rounded-md hover:bg-accent transition-colors"
                title="Copy Account ID"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium mt-2
              ${account.status === 'connected' ? 'bg-green-500/10 text-green-500' :
                account.status === 'connecting' ? 'bg-yellow-500/10 text-yellow-500' :
                account.status === 'error' ? 'bg-red-500/10 text-red-500' :
                'bg-muted text-muted-foreground'}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${getStatusDot(account.status)}`} />
              {account.status}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 mt-4 pt-4 border-t border-border">
          {account.status !== 'connected' && (
            <button
              onClick={() => {
                if (account.status === 'disconnected' || account.status === 'error') {
                  handleReconnect();
                } else {
                  setShowQR(true);
                }
              }}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg bg-whatsapp px-3 py-2 text-xs font-semibold text-white hover:bg-whatsapp-dark transition-colors disabled:opacity-50"
            >
              <QrCode className="h-3.5 w-3.5" />
              {account.status === 'connecting' ? 'Show QR' : 'Connect'}
            </button>
          )}

          {account.status === 'connected' && (
            <button
              onClick={handleDisconnect}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-medium hover:bg-accent transition-colors disabled:opacity-50"
            >
              <Unplug className="h-3.5 w-3.5" />
              Disconnect
            </button>
          )}

          <button
            onClick={handleReconnect}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-medium hover:bg-accent transition-colors disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Reconnect
          </button>

          <button
            onClick={handleDelete}
            disabled={loading}
            className="ml-auto flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </button>
        </div>
      </div>

      {showQR && (
        <QRModal account={account} onClose={() => { setShowQR(false); onRefresh(); }} />
      )}
    </>
  );
}

export default function WhatsAppPage() {
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [newAccountId, setNewAccountId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { on } = useWebSocket();

  const loadAccounts = useCallback(async () => {
    try {
      setLoadError(null);
      const res = await whatsappApi.listAccounts();
      setAccounts(res.data);
    } catch (err) {
      console.error('Failed to load accounts', err);
      setLoadError('Failed to load accounts. Please check your connection and try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  useEffect(() => {
    const unsub1 = on('account_connected', () => loadAccounts());
    const unsub2 = on('account_disconnected', () => loadAccounts());
    return () => { unsub1(); unsub2(); };
  }, [on, loadAccounts]);

  useEffect(() => {
    const hasConnecting = accounts.some(a => a.status === 'connecting');
    if (!hasConnecting) return;

    const interval = setInterval(() => {
      loadAccounts();
    }, 2500);

    return () => clearInterval(interval);
  }, [accounts, loadAccounts]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await whatsappApi.createAccount(newName.trim());
      const account = res.data;
      setNewName('');
      setShowForm(false);
      await loadAccounts();
      setNewAccountId(account.id);
      toast.success(`Account "${account.name}" created`);
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to create account');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">WhatsApp Accounts</h1>
          <p className="text-muted-foreground mt-1">Connect and manage your WhatsApp numbers</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2.5 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add Account
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="rounded-xl border border-border bg-card p-5 mb-6">
          <h3 className="font-semibold mb-4">New WhatsApp Account</h3>
          <div className="flex gap-3">
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Account name (e.g. Customer Support)"
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
          <p className="text-xs text-muted-foreground mt-3">
            After creating, you'll scan a QR code to link your WhatsApp.
          </p>
        </form>
      )}

      {/* Account list */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : loadError ? (
        <div className="flex flex-col items-center justify-center py-16 text-center rounded-xl border border-red-500/20 bg-red-500/5 p-6">
          <p className="font-semibold text-red-500">{loadError}</p>
          <button
            onClick={loadAccounts}
            className="mt-4 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-500 px-4 py-2 text-sm font-medium transition-colors"
          >
            Retry Connection
          </button>
        </div>
      ) : accounts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center rounded-xl border border-dashed border-border">
          <Smartphone className="h-12 w-12 text-muted-foreground mb-4" />
          <p className="font-medium">No accounts yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Add your first WhatsApp account to start receiving messages
          </p>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
          >
            <Plus className="h-4 w-4" /> Add Account
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {accounts.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              onRefresh={loadAccounts}
            />
          ))}
        </div>
      )}

      {/* Show QR for newly created account */}
      {newAccountId && (() => {
        const account = accounts.find(a => a.id === newAccountId);
        if (!account) return null;
        return (
          <QRModal
            account={account}
            onClose={() => { setNewAccountId(null); loadAccounts(); }}
          />
        );
      })()}
    </div>
  );
}
