'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  BookOpen, Upload, FileText, Trash2, CheckCircle2,
  AlertCircle, Loader2, Eye, X, FileCheck, ToggleLeft, ToggleRight
} from 'lucide-react';
import { whatsappApi, documentsApi } from '@/lib/api';
import { WhatsAppAccount, Document, DocumentDetail } from '@/types';
import { toast } from 'sonner';

function formatBytes(bytes: number, decimals = 1) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

export default function KnowledgeBasePage() {
  const [accounts, setAccounts] = useState<WhatsAppAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<DocumentDetail | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Load WhatsApp Accounts
  const loadAccounts = useCallback(async () => {
    try {
      const res = await whatsappApi.listAccounts();
      setAccounts(res.data);
      if (res.data.length > 0 && !selectedAccountId) {
        setSelectedAccountId(res.data[0].id);
      }
    } catch (err) {
      console.error('Failed to load accounts', err);
      toast.error('Failed to load WhatsApp accounts');
    } finally {
      setLoading(false);
    }
  }, [selectedAccountId]);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  // Load Documents for selected account
  const loadDocuments = useCallback(async () => {
    if (!selectedAccountId) return;
    try {
      const res = await documentsApi.list(selectedAccountId);
      setDocuments(res.data);
    } catch (err) {
      console.error('Failed to load documents', err);
      toast.error('Failed to load knowledge documents');
    }
  }, [selectedAccountId]);

  useEffect(() => {
    if (selectedAccountId) {
      loadDocuments();
    }
  }, [selectedAccountId, loadDocuments]);

  // Handle file upload
  const handleUploadFile = async (file: File) => {
    if (!selectedAccountId) {
      toast.error('Please select a WhatsApp account first');
      return;
    }

    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!ext || !['pdf', 'txt', 'csv', 'md', 'json'].includes(ext)) {
      toast.error('Unsupported file type. Please upload PDF, TXT, CSV, or MD files.');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      toast.error('File size exceeds 10 MB limit');
      return;
    }

    setUploading(true);
    try {
      await documentsApi.upload(selectedAccountId, file);
      toast.success(`"${file.name}" indexed successfully into Knowledge Base!`);
      await loadDocuments();
    } catch (err: any) {
      console.error('Upload failed', err);
      toast.error(err.response?.data?.detail || 'Failed to upload document');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUploadFile(e.dataTransfer.files[0]);
    }
  };

  const handleToggle = async (docId: string) => {
    try {
      const res = await documentsApi.toggle(docId);
      setDocuments(prev =>
        prev.map(d => (d.id === docId ? { ...d, is_active: res.data.is_active } : d))
      );
      toast.success(res.data.is_active ? 'Document activated' : 'Document deactivated');
    } catch (err) {
      toast.error('Failed to update document status');
    }
  };

  const handleDelete = async (docId: string, filename: string) => {
    if (!confirm(`Are you sure you want to delete "${filename}" from knowledge base?`)) return;
    try {
      await documentsApi.delete(docId);
      setDocuments(prev => prev.filter(d => d.id !== docId));
      toast.success('Document deleted');
    } catch (err) {
      toast.error('Failed to delete document');
    }
  };

  const handlePreview = async (docId: string) => {
    setLoadingPreview(true);
    try {
      const res = await documentsApi.get(docId);
      setPreviewDoc(res.data);
    } catch (err) {
      toast.error('Failed to load document content');
    } finally {
      setLoadingPreview(false);
    }
  };

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2.5">
            <BookOpen className="h-6 w-6 text-whatsapp" /> Knowledge Base (RAG)
          </h1>
          <p className="text-muted-foreground mt-1">
            Upload your price list, product catalog, or FAQs. The AI will answer customer questions strictly using this data.
          </p>
        </div>
      </div>

      {/* Account Selector */}
      {accounts.length > 1 && (
        <div className="mb-6 flex items-center gap-3">
          <label className="text-sm font-medium text-muted-foreground">Active WhatsApp Account:</label>
          <select
            value={selectedAccountId}
            onChange={(e) => setSelectedAccountId(e.target.value)}
            className="rounded-lg border border-input bg-background px-3 py-1.5 text-sm outline-none focus:border-whatsapp"
          >
            {accounts.map(acc => (
              <option key={acc.id} value={acc.id}>{acc.name} ({acc.phone_number || 'Unlinked'})</option>
            ))}
          </select>
        </div>
      )}

      {/* Upload Box */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition-all ${
          isDragging
            ? 'border-whatsapp bg-whatsapp/5'
            : 'border-border hover:border-whatsapp/50 bg-card hover:bg-accent/40'
        } mb-8`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,.csv,.md,.json"
          onChange={(e) => e.target.files?.[0] && handleUploadFile(e.target.files[0])}
          className="hidden"
        />

        <div className="flex flex-col items-center justify-center">
          {uploading ? (
            <>
              <Loader2 className="h-10 w-10 animate-spin text-whatsapp mb-3" />
              <p className="font-semibold text-sm">Processing & Indexing Document...</p>
              <p className="text-xs text-muted-foreground mt-1">Extracting text for Gemini 2.0 Flash</p>
            </>
          ) : (
            <>
              <div className="h-12 w-12 rounded-xl bg-whatsapp/10 text-whatsapp flex items-center justify-center mb-3">
                <Upload className="h-6 w-6" />
              </div>
              <p className="font-semibold text-sm">
                Click to upload or drag & drop business files
              </p>
              <p className="text-xs text-muted-foreground mt-1.5">
                Supports PDF, TXT, CSV, Markdown, JSON (up to 10 MB)
              </p>
            </>
          )}
        </div>
      </div>

      {/* Documents List */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <FileCheck className="h-4 w-4 text-whatsapp" /> Uploaded Knowledge Documents ({documents.length})
          </h2>
          <span className="text-xs text-muted-foreground">Active documents are automatically fed to AI</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center py-16 px-4">
            <FileText className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-40" />
            <p className="font-medium text-sm">No knowledge documents uploaded yet</p>
            <p className="text-xs text-muted-foreground mt-1">
              Upload your company menu, pricing, or FAQ document to train your bot.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="px-6 py-4 flex items-center justify-between hover:bg-accent/30 transition-colors"
              >
                <div className="flex items-center gap-3.5 min-w-0">
                  <div className="h-9 w-9 rounded-lg bg-whatsapp/10 text-whatsapp flex items-center justify-center shrink-0">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm truncate max-w-sm">{doc.filename}</p>
                      <span className="uppercase text-[10px] font-bold px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                        {doc.file_type}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {formatBytes(doc.file_size)} • Uploaded {new Date(doc.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {/* Status toggle */}
                  <button
                    onClick={() => handleToggle(doc.id)}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                      doc.is_active
                        ? 'bg-whatsapp/10 text-whatsapp hover:bg-whatsapp/20'
                        : 'bg-muted text-muted-foreground hover:bg-muted/80'
                    }`}
                    title={doc.is_active ? 'Click to disable' : 'Click to enable'}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${doc.is_active ? 'bg-whatsapp' : 'bg-muted-foreground'}`} />
                    {doc.is_active ? 'Active' : 'Disabled'}
                  </button>

                  {/* Preview Button */}
                  <button
                    onClick={() => handlePreview(doc.id)}
                    className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-colors"
                    title="View extracted text"
                  >
                    <Eye className="h-4 w-4" />
                  </button>

                  {/* Delete Button */}
                  <button
                    onClick={() => handleDelete(doc.id, doc.filename)}
                    className="p-1.5 text-muted-foreground hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-colors"
                    title="Delete document"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Text Preview Modal */}
      {previewDoc && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-2xl max-w-2xl w-full max-h-[80vh] flex flex-col shadow-2xl">
            <div className="px-6 py-4 border-b border-border flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-sm">{previewDoc.filename}</h3>
                <p className="text-xs text-muted-foreground">Extracted Knowledge Text Preview</p>
              </div>
              <button
                onClick={() => setPreviewDoc(null)}
                className="p-1 text-muted-foreground hover:text-foreground rounded-lg"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto font-mono text-xs whitespace-pre-wrap leading-relaxed text-muted-foreground bg-muted/20">
              {previewDoc.extracted_text}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
