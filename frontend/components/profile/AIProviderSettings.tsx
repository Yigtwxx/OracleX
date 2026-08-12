'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Bot, Check, Loader2, Trash2, AlertTriangle } from 'lucide-react';
import ProfileCard from '@/components/profile/ProfileCard';
import {
  deleteLLMSettings,
  getLLMSettings,
  testLLMSettings,
  updateLLMSettings,
  type LLMSettings,
} from '@/lib/api';

type Feature = 'use_for_chat' | 'use_for_news' | 'use_for_reports';

const FEATURE_LABELS: { key: Feature; label: string; hint: string }[] = [
  { key: 'use_for_chat', label: 'Oracle Chat', hint: 'Chat responses' },
  { key: 'use_for_news', label: 'News analysis', hint: 'When you click a headline to analyze it' },
  { key: 'use_for_reports', label: 'Reports', hint: 'Report generation on the Analysis page' },
];

export default function AIProviderSettings() {
  const [settings, setSettings] = useState<LLMSettings | undefined>(undefined);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | undefined>(undefined);
  const [models, setModels] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await getLLMSettings();
      setSettings(data);
      setProvider(data.provider || data.supported_providers[0] || '');
      setModel(data.model);
    } catch {
      setMessage({ ok: false, text: 'Could not load settings.' });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!settings) {
    // A shimmer at the loaded card's footprint, matching the rest of the app —
    // a bare spinner leaves the page height jumping when the data lands.
    return <div className="surface shimmer h-72" />;
  }

  const handleTest = async () => {
    if (!apiKey) {
      setMessage({ ok: false, text: 'Enter a key to test.' });
      return;
    }
    setBusy(true);
    setMessage(undefined);
    try {
      const result = await testLLMSettings(provider, model, apiKey);
      setModels(result.models ?? []);
      setMessage(
        result.ok
          ? { ok: true, text: `Connection OK — ${result.models?.length ?? 0} models found.` }
          : { ok: false, text: result.error ?? 'Key could not be verified.' }
      );
    } catch {
      setMessage({ ok: false, text: 'Test request failed.' });
    } finally {
      setBusy(false);
    }
  };

  const save = async (overrides: Partial<Record<Feature, boolean>> = {}) => {
    setBusy(true);
    setMessage(undefined);
    try {
      const updated = await updateLLMSettings({
        provider,
        model,
        api_key: apiKey || undefined,
        use_for_chat: overrides.use_for_chat ?? settings.use_for_chat,
        use_for_news: overrides.use_for_news ?? settings.use_for_news,
        use_for_reports: overrides.use_for_reports ?? settings.use_for_reports,
      });
      setSettings({ ...settings, ...updated });
      setApiKey('');
      setMessage({ ok: true, text: 'Saved.' });
    } catch (error) {
      setMessage({
        ok: false,
        text: error instanceof Error ? error.message : 'Could not save.',
      });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    setBusy(true);
    try {
      await deleteLLMSettings();
      setApiKey('');
      setModels([]);
      await load();
      setMessage({ ok: true, text: 'Deleted — the server provider will be used.' });
    } catch {
      setMessage({ ok: false, text: 'Could not delete.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProfileCard title="AI Provider" icon={Bot}>
      <div className="space-y-5">
        {!settings.encryption_available && (
          <div className="flex items-start gap-2 p-3 rounded-md bg-warn-bg border border-warn text-warn text-base">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>
              <code>LLM_KEY_ENCRYPTION_SECRET</code> is not set on the server, so your own key
              cannot be stored.
            </span>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <span className="label">Provider</span>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="mt-1 w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-line text-fg text-base focus:outline-none focus:border-accent"
            >
              {settings.supported_providers.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label">Model (blank = default)</span>
            <input
              list="llm-model-options"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. qwen/qwen3.6-27b"
              className="mt-1 w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-line text-fg text-base focus:outline-none focus:border-accent"
            />
            <datalist id="llm-model-options">
              {models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </label>
        </div>

        <label className="block">
          <span className="label">
            API key
            {settings.configured && ` — saved (…${settings.key_hint})`}
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              settings.configured ? 'Enter a new key to replace it' : 'Paste your API key'
            }
            autoComplete="off"
            className="mt-1 w-full px-2.5 py-1.5 rounded-md bg-surface-2 border border-line text-fg text-base font-mono focus:outline-none focus:border-accent"
          />
        </label>

        <div>
          <p className="label mb-2">Use my key for:</p>
          <div className="space-y-2">
            {FEATURE_LABELS.map(({ key, label, hint }) => (
              <button
                key={key}
                type="button"
                disabled={busy || !settings.configured}
                onClick={() => void save({ [key]: !settings[key] })}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-md border text-base transition-colors disabled:opacity-40 ${
                  settings[key]
                    ? 'bg-accent-bg border-accent text-fg'
                    : 'bg-surface-2 border-line text-fg-muted'
                }`}
              >
                <span className="text-left">
                  {label}
                  <span className="block text-xs text-fg-subtle">{hint}</span>
                </span>
                {settings[key] && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>
            ))}
          </div>
          <p className="text-xs text-fg-subtle mt-3">
            The background news scan that runs every two minutes always uses the server provider —
            those requests have no user context.
          </p>
        </div>

        {message && (
          <p className={`text-sm ${message.ok ? 'text-up' : 'text-down'}`}>{message.text}</p>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleTest()}
            className="px-3 py-1.5 rounded-md bg-surface-2 border border-line text-base text-fg-muted hover:text-fg transition-colors disabled:opacity-40"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Test'}
          </button>
          <button
            type="button"
            disabled={busy || !settings.encryption_available}
            onClick={() => void save()}
            className="px-3 py-1.5 rounded-md bg-accent text-white text-base hover:opacity-90 transition-opacity disabled:opacity-40"
          >
            Save
          </button>
          {settings.configured && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleDelete()}
              className="px-3 py-1.5 rounded-md bg-down-bg border border-down text-base text-down flex items-center gap-1.5 disabled:opacity-40"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete
            </button>
          )}
        </div>
      </div>
    </ProfileCard>
  );
}
