'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { Bot, Save, Loader2, Settings2, Sun, Moon, Mic, Play, Square, Volume2, Sparkles, Globe, Smile } from 'lucide-react';
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

const PERSONA_PRESETS = [
  {
    id: 'vibe_tamil',
    name: '🌟 Vibe AI (Tamil & Tanglish Buddy)',
    badge: 'Popular',
    desc: 'Fluent spoken Tamil (பேச்சுத் தமிழ்) + modern Tanglish friend. Charismatic, natural, and authentic.',
    prompt: `You are a charismatic, super-friendly, and helpful AI buddy chatting on WhatsApp.

## 🗣️ LANGUAGE & SLANG MASTERY
- Flawlessly understand Tamil (தமிழ்), Tanglish (Tamil written in English letters like "machan", "epdi irukka", "enna pandra", "romba nandri"), and English.
- Always mirror the user's language style:
  • If user speaks/texts in Tanglish: reply in smooth, natural Tanglish with cool friendly emojis.
  • If user speaks/texts in Tamil script: reply in natural spoken Tamil.
  • If user speaks/texts in English: reply in relaxed, conversational English.
- Use natural spoken colloquial Tamil (பேச்சுத் தமிழ்): e.g., "சொல்லுங்க", "எப்படி இருக்கீங்க?", "கண்டிப்பா", "அப்டியா", "நோ பிராப்ளம்", "சூப்பர்". Avoid stiff or bookish formal phrasing.

## 🎙️ VOICE NOTE SPEECH RULES
- When generating voice notes, keep the speech smooth, relaxed, and easy to understand.
- Never pronounce English letters mechanically for Tamil words. The speech track uses Tamil script so the native Tamil neural voice speaks authentically.
- Zero asterisks, zero markdown, zero bullet points in the speech track.
- Never announce the clock time unless explicitly asked.

## ⚡ BEHAVIOR & ETIQUETTE
- Sound like a real, thoughtful human talking naturally.
- Keep responses concise, warm, and engaging.
- Never hallucinate business facts or invent policies.`,
    recommendedVoice: 'ta-IN-ValluvarNeural',
  },
  {
    id: 'pro_business',
    name: '💼 Professional Business Assistant',
    badge: 'Business',
    desc: 'Courteous, polite, and structured assistant for sales, bookings, and customer inquiries.',
    prompt: `You are an elite, highly professional WhatsApp customer support assistant for our business.

## 🎯 CORE PRINCIPLES
1. Always maintain a polite, respectful, and reassuring tone (மரியாதையான அணுகுமுறை).
2. Answer strictly using official verified business knowledge base information. Never invent prices, discounts, delivery times, or policies.
3. If an answer is not in the knowledge base, politely inform the customer and offer to connect them with a human specialist.

## 🌐 LANGUAGE CAPABILITIES
- Support English, Tamil (தமிழ்), and Tanglish seamlessly.
- For Tamil customers, communicate with warm professional respect: "வணக்கம்! எங்கள் நிறுவனத்திற்கு தங்களை வரவேற்கிறோம். தங்களுக்கு எவ்வாறு உதவ முடியும்?".
- Keep answers clear, well-structured, and easy to read on mobile screens.

## 🎙️ VOICE NOTE PROTOCOL
- Deliver clear, calm, and articulate voice responses.
- Pace the speech naturally with clear pronunciation and courteous phrasing.
- Zero markdown syntax or emoji names in spoken audio.`,
    recommendedVoice: 'ta-IN-PallaviNeural',
  },
  {
    id: 'tech_mentor',
    name: '⚡ Tech & Code Mentor',
    badge: 'Developer',
    desc: 'Senior engineer buddy who explains code, logic, and debugging in Tamil & English.',
    prompt: `You are a brilliant and practical senior engineer and tech mentor assisting developers on WhatsApp.

## 🚀 EXPERTISE & STYLE
- Explain complex programming concepts, bugs, system architecture, and logic simply and practically.
- Blend Tamil and English smoothly when communicating with Tamil developers (e.g. "API endpoint-la authentication header miss aagudhu, adha check pannunga").
- Provide clean, minimal, production-ready code snippets when requested.

## 🎙️ VOICE NOTES
- Explain code flow and debugging steps logically and clearly, as if pairing together in a coffee shop.
- Avoid reading out long syntax or brackets in voice notes; explain the high-level logic in speech and provide exact code in text.`,
    recommendedVoice: 'en-IN-PrabhatNeural',
  },
];

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
    voice_name: 'en-IN-PrabhatNeural',
    voice_reply_mode: 'audio_only',
    web_search_enabled: true,
    stickers_enabled: true,
    groq_api_key: '',
  });

  const [loadError, setLoadError] = useState<string | null>(null);

  // Audio Preview State
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopPreview = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    setPlayingVoice(null);
    setPreviewLoading(false);
  };

  const handlePreviewVoice = async (voiceName: string) => {
    if (playingVoice === voiceName) {
      stopPreview();
      return;
    }
    stopPreview();
    setPreviewLoading(true);
    setPlayingVoice(voiceName);

    try {
      const res = await botApi.previewVoice(voiceName);
      const audioBlob = new Blob([res.data], { type: 'audio/mpeg' });
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      audioRef.current = audio;

      audio.onended = () => {
        setPlayingVoice(null);
        audioRef.current = null;
      };
      audio.onerror = () => {
        toast.error('Failed to play voice sample');
        stopPreview();
      };

      await audio.play();
    } catch (err) {
      console.error('Failed to preview voice', err);
      toast.error('Voice preview failed. Please try again.');
      stopPreview();
    } finally {
      setPreviewLoading(false);
    }
  };

  // Cleanup audio on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
      }
    };
  }, []);

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
          voice_name: res.data.voice_name ?? 'en-IN-PrabhatNeural',
          voice_reply_mode: res.data.voice_reply_mode ?? 'audio_only',
          web_search_enabled: res.data.web_search_enabled ?? true,
          stickers_enabled: res.data.stickers_enabled ?? true,
          groq_api_key: res.data.groq_api_key ?? '',
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

  const applyPreset = (preset: typeof PERSONA_PRESETS[0]) => {
    setForm(f => ({
      ...f,
      system_prompt: preset.prompt,
      voice_name: preset.recommendedVoice,
    }));
    toast.success(`Applied preset: ${preset.name}`);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-1">Configure your AI bot behavior, persona, and voice synthesis</p>
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
                <option value="automatic">Automatic (match customer language)</option>
                <option value="tamil">Tamil / Tanglish (தமிழ்)</option>
                <option value="english">English</option>
                <option value="hindi">Hindi (हिंदी)</option>
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

            {/* Google Search Grounding */}
            <div className="flex items-center justify-between rounded-xl border border-border/70 bg-muted/15 p-4">
              <div className="pr-4">
                <p className="text-sm font-semibold flex items-center gap-2">
                  <Globe className="h-4 w-4 text-blue-500" /> Live Web Search Grounding (Real-Time Knowledge)
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Empowers Gemini to search the web in real-time for live cricket scores, latest weather, breaking news, cinema releases, and current events.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, web_search_enabled: !f.web_search_enabled }))}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${form.web_search_enabled ? 'bg-whatsapp' : 'bg-muted'}`}
              >
                <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.web_search_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* WhatsApp Sticker Creator */}
            <div className="flex items-center justify-between rounded-xl border border-border/70 bg-muted/15 p-4">
              <div className="pr-4">
                <p className="text-sm font-semibold flex items-center gap-2">
                  <Smile className="h-4 w-4 text-amber-500" /> Instant WhatsApp Sticker Creator
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Automatically converts photos sent by contacts with caption <code className="bg-background px-1 py-0.5 rounded text-[11px] font-mono">sticker</code> or <code className="bg-background px-1 py-0.5 rounded text-[11px] font-mono">ஸ்டிக்கர்</code> into native 512×512 WhatsApp stickers.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, stickers_enabled: !f.stickers_enabled }))}
                className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${form.stickers_enabled ? 'bg-whatsapp' : 'bg-muted'}`}
              >
                <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.stickers_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>

            {/* AI Voice Note Replies (TTS) */}
            <div className="rounded-xl border border-border/80 bg-muted/20 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold flex items-center gap-2">
                    <Mic className="h-4 w-4 text-whatsapp" /> AI Voice Note Replies (Ultra TTS Engine)
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Synthesizes 24kHz HD Wideband Opus audio with native Tamil and English phonetics
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
                <div className="space-y-4 pt-3 border-t border-border/50">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Voice Accent Selector with Live Preview */}
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs font-medium">Voice Accent & Model</label>
                        <button
                          type="button"
                          onClick={() => handlePreviewVoice(form.voice_name)}
                          disabled={previewLoading && playingVoice !== form.voice_name}
                          className="flex items-center gap-1 text-[11px] font-semibold text-whatsapp hover:text-whatsapp-dark bg-whatsapp/10 hover:bg-whatsapp/20 px-2 py-0.5 rounded transition-colors"
                        >
                          {previewLoading && playingVoice === form.voice_name ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : playingVoice === form.voice_name ? (
                            <>
                              <Square className="h-3 w-3 fill-current text-red-500" />
                              <span className="text-red-500">Stop</span>
                            </>
                          ) : (
                            <>
                              <Volume2 className="h-3 w-3" />
                              <span>▶️ Listen</span>
                            </>
                          )}
                        </button>
                      </div>

                      <select
                        value={form.voice_name}
                        onChange={(e) => {
                          stopPreview();
                          setForm(f => ({ ...f, voice_name: e.target.value }));
                        }}
                        className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none focus:border-whatsapp"
                      >
                        <optgroup label="🇮🇳 Native Tamil Voices (Authentic Spoken Tamil)">
                          <option value="ta-IN-ValluvarNeural">🇮🇳 Tamil Male — Valluvar (Smooth & Authentic)</option>
                          <option value="ta-IN-PallaviNeural">🇮🇳 Tamil Female — Pallavi (Expressive & Warm)</option>
                        </optgroup>
                        <optgroup label="🇮🇳 Indian English (Fluent & Natural)">
                          <option value="en-IN-PrabhatNeural">🇮🇳 Indian English Male — Prabhat (Charismatic)</option>
                          <option value="en-IN-NeerjaNeural">🇮🇳 Indian English Female — Neerja (Crisp)</option>
                        </optgroup>
                        <optgroup label="🇮🇳 Hindi Voices">
                          <option value="hi-IN-MadhurNeural">🇮🇳 Hindi Male — Madhur</option>
                          <option value="hi-IN-SwaraNeural">🇮🇳 Hindi Female — Swara</option>
                        </optgroup>
                        <optgroup label="🇺🇸 Global English">
                          <option value="en-US-JennyNeural">🇺🇸 US English Female — Jenny</option>
                          <option value="en-US-GuyNeural">🇺🇸 US English Male — Guy</option>
                        </optgroup>
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

                  {/* Groq API Key Input */}
                  <div className="rounded-lg bg-background/60 border border-border/60 p-3">
                    <label className="block text-xs font-medium mb-1">
                      Groq API Key <span className="text-muted-foreground font-normal">(Enables ~150ms ultra-fast Whisper audio transcription)</span>
                    </label>
                    <input
                      type="password"
                      placeholder="gsk_..."
                      value={form.groq_api_key || ''}
                      onChange={(e) => setForm(f => ({ ...f, groq_api_key: e.target.value }))}
                      className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none focus:border-whatsapp font-mono"
                    />
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Get a free key from <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" className="text-whatsapp underline font-medium">console.groq.com</a>. Incoming WhatsApp voice notes in Tamil or English are transcribed in 150ms so Gemini replies instantly.
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Persona Presets */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold flex items-center gap-1.5">
                  <Sparkles className="h-4 w-4 text-amber-500" /> Persona Presets
                </label>
                <span className="text-xs text-muted-foreground">Click a preset to apply full optimized prompt & voice</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {PERSONA_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => applyPreset(preset)}
                    className="text-left p-3.5 rounded-xl border border-border/70 hover:border-whatsapp/80 bg-background/50 hover:bg-whatsapp/5 transition-all group flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-bold group-hover:text-whatsapp transition-colors line-clamp-1">
                          {preset.name}
                        </span>
                        <span className="text-[10px] bg-muted px-1.5 py-0.5 rounded text-muted-foreground font-medium">
                          {preset.badge}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">
                        {preset.desc}
                      </p>
                    </div>
                    <span className="mt-2 text-[10px] text-whatsapp font-semibold group-hover:underline">
                      Apply Preset →
                    </span>
                  </button>
                ))}
              </div>
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
                rows={12}
                className="w-full rounded-lg border border-input bg-background px-4 py-3 text-sm outline-none focus:border-primary font-mono resize-y leading-relaxed"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Customize the AI's personality, colloquial slang, and business instructions.
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
