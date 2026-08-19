'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Smartphone, MessageSquare, Bot, Users,
  TrendingUp, Plus, ArrowRight, CheckCircle2, XCircle, Clock
} from 'lucide-react';
import { dashboardApi, whatsappApi } from '@/lib/api';
import { DashboardStats, WhatsAppAccount } from '@/types';
import { getStatusDot, formatRelativeTime } from '@/lib/utils';
import { useWebSocket } from '@/hooks/useWebSocket';
import { toast } from 'sonner';

function StatCard({
  label, value, icon: Icon, description, color = 'text-foreground'
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  description?: string;
  color?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
          {description && (
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
          )}
        </div>
        <div className="rounded-lg bg-muted p-2.5">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const { on } = useWebSocket();

  const load = async () => {
    try {
      const [statsRes, accountsRes] = await Promise.all([
        dashboardApi.getStats(),
        whatsappApi.listAccounts(),
      ]);
      setStats(statsRes.data);
      setAccounts(accountsRes.data);
    } catch (err) {
      console.error('Failed to load dashboard', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Refresh on WS events
  useEffect(() => {
    const unsub1 = on('account_connected', () => load());
    const unsub2 = on('account_disconnected', () => load());
    const unsub3 = on('message_received', () => load());
    return () => { unsub1(); unsub2(); unsub3(); };
  }, [on]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-border border-t-primary" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground mt-1">Your WhatsApp AI overview</p>
        </div>
        <Link
          href="/whatsapp"
          className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2.5 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
        >
          <Plus className="h-4 w-4" />
          Add Account
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Connected Accounts"
          value={stats?.connected_accounts ?? 0}
          icon={Smartphone}
          color="text-green-500"
        />
        <StatCard
          label="Messages Today"
          value={stats?.messages_today ?? 0}
          icon={MessageSquare}
        />
        <StatCard
          label="AI Replies Today"
          value={stats?.ai_replies_today ?? 0}
          icon={Bot}
          color="text-whatsapp"
        />
        <StatCard
          label="Active Conversations"
          value={stats?.active_conversations ?? 0}
          icon={Users}
        />
      </div>

      {/* Accounts */}
      <div className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="font-semibold">WhatsApp Accounts</h2>
          <Link
            href="/whatsapp"
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Manage <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>

        {accounts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Smartphone className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-sm font-medium">No WhatsApp accounts</p>
            <p className="text-xs text-muted-foreground mt-1 mb-4">
              Connect your first WhatsApp account to get started
            </p>
            <Link
              href="/whatsapp"
              className="flex items-center gap-2 rounded-lg bg-whatsapp px-4 py-2 text-sm font-semibold text-white hover:bg-whatsapp-dark transition-colors"
            >
              <Plus className="h-4 w-4" /> Add Account
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {accounts.map((account) => (
              <div key={account.id} className="flex items-center gap-4 px-6 py-4">
                <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-whatsapp/10">
                  <Smartphone className="h-5 w-5 text-whatsapp" />
                  <span
                    className={`absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-card ${getStatusDot(account.status)}`}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-sm">{account.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {account.phone_number || 'Not connected yet'}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-medium capitalize
                  ${account.status === 'connected' ? 'bg-green-500/10 text-green-500' :
                    account.status === 'connecting' ? 'bg-yellow-500/10 text-yellow-500' :
                    account.status === 'error' ? 'bg-red-500/10 text-red-500' :
                    'bg-muted text-muted-foreground'}`}
                >
                  {account.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick Links */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6">
        {[
          { href: '/conversations', label: 'View Conversations', icon: MessageSquare, desc: 'See all messages' },
          { href: '/settings', label: 'Configure AI', icon: Bot, desc: 'Manage bot settings' },
          { href: '/api-keys', label: 'API Keys', icon: TrendingUp, desc: 'Integrate your app' },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-xl border border-border bg-card p-5 hover:bg-accent transition-colors group"
          >
            <item.icon className="h-6 w-6 text-muted-foreground mb-3 group-hover:text-foreground transition-colors" />
            <p className="font-medium text-sm">{item.label}</p>
            <p className="text-xs text-muted-foreground mt-1">{item.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
