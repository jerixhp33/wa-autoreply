import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// Inject auth token
api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// Handle 401 globally
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (email: string, password: string) =>
    api.post('/api/auth/login', { email, password }),

  register: (email: string, name: string, password: string) =>
    api.post('/api/auth/register', { email, name, password }),

  me: () => api.get('/api/auth/me'),
};

// ─── WhatsApp ─────────────────────────────────────────────────────────────────

export const whatsappApi = {
  listAccounts: () => api.get('/api/whatsapp/accounts'),

  createAccount: (name: string) =>
    api.post('/api/whatsapp/accounts', { name }),

  getAccount: (id: string) =>
    api.get(`/api/whatsapp/accounts/${id}`),

  getQR: (id: string) =>
    api.get(`/api/whatsapp/accounts/${id}/qr`),

  disconnect: (id: string) =>
    api.post(`/api/whatsapp/accounts/${id}/disconnect`),

  reconnect: (id: string) =>
    api.post(`/api/whatsapp/accounts/${id}/reconnect`),

  deleteAccount: (id: string) =>
    api.delete(`/api/whatsapp/accounts/${id}`),
};

// ─── Conversations ────────────────────────────────────────────────────────────

export const conversationsApi = {
  list: (accountId?: string) =>
    api.get('/api/conversations', { params: accountId ? { account_id: accountId } : {} }),

  get: (id: string) => api.get(`/api/conversations/${id}`),

  getMessages: (id: string, limit = 50, offset = 0) =>
    api.get(`/api/conversations/${id}/messages`, { params: { limit, offset } }),

  update: (id: string, data: { ai_enabled?: boolean; human_takeover?: boolean }) =>
    api.patch(`/api/conversations/${id}`, data),
};

// ─── Messages ─────────────────────────────────────────────────────────────────

export const messagesApi = {
  send: (accountId: string, phone: string, message: string) =>
    api.post('/api/messages/send', { account_id: accountId, phone, message }),
};

// ─── Bot Settings ─────────────────────────────────────────────────────────────

export const botApi = {
  getSettings: (accountId: string) =>
    api.get(`/api/bot/settings/${accountId}`),

  updateSettings: (accountId: string, data: Record<string, unknown>) =>
    api.put(`/api/bot/settings/${accountId}`, data),

  previewVoice: (voice_name: string, sample_text?: string) =>
    api.post('/api/bot/tts/preview', { voice_name, sample_text }, { responseType: 'blob' }),
};

// ─── API Keys ─────────────────────────────────────────────────────────────────

export const apiKeysApi = {
  list: () => api.get('/api/api-keys'),
  create: (name: string) => api.post('/api/api-keys', { name }),
  revoke: (id: string) => api.delete(`/api/api-keys/${id}`),
};

// ─── Dashboard ────────────────────────────────────────────────────────────────

export const dashboardApi = {
  getStats: () => api.get('/api/dashboard/stats'),
};

// ─── Documents (Knowledge Base) ───────────────────────────────────────────────

export const documentsApi = {
  list: (accountId: string) =>
    api.get('/api/documents', { params: { account_id: accountId } }),

  get: (documentId: string) =>
    api.get(`/api/documents/${documentId}`),

  upload: (accountId: string, file: File) => {
    const formData = new FormData();
    formData.append('account_id', accountId);
    formData.append('file', file);
    return api.post('/api/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  toggle: (documentId: string) =>
    api.patch(`/api/documents/${documentId}/toggle`),

  delete: (documentId: string) =>
    api.delete(`/api/documents/${documentId}`),
};

