'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Bot, Loader2, Trash2, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import ProfileCard from '@/components/profile/ProfileCard';
import {
  deleteLLMSettings,
  getLLMSettings,
  testLLMSettings,
  updateLLMSettings,
  type LLMSettings,
} from '@/lib/api';

type Feature = 'use_for_chat' | 'use_for_news' | 'use_for_reports' | 'use_for_notes';

/**
 * What each stored column actually governs, rather than what it is named after.
 *
 * `use_for_reports` resolves the provider at four call sites, not one — the
 * Analysis report stages, Polymarket bet synthesis and Polymarket origin — and
 * `use_for_chat` covers the planner behind a reply as well as the reply. A user
 * deciding whether to spend their own quota cannot make that call from a label
 * reading "Report generation on the Analysis page".
 */
const FEATURES: { key: Feature; label: string; hint: string }[] = [
  {
    key: 'use_for_chat',
    label: 'Oracle Chat',
    hint: 'Replies, and the planner that decides which tools a question needs',
  },
  {
    key: 'use_for_news',
    label: 'News analysis',
    hint: 'A headline you open for analysis',
  },
  {
    key: 'use_for_reports',
    label: 'Reports & bet analysis',
    hint: 'Market reports on Analysis, plus Polymarket bet synthesis and origin',
  },
  {
    key: 'use_for_notes',
    label: 'AI notes',
    hint: 'The short reads under asset briefs, macro, ownership, chains and every BIST board',
  },
];

// Lifted from `components/alarms/controls.tsx`, which collected the app's form
// vocabulary because `components/ui/` has no Input or Button primitive. Imported
// rather than re-typed would couple Profile to Alarms; the real fix is to move
// that module under `components/ui/`, which is wider than this card.
const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg transition-colors placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-50';

export default function AIProviderSettings() {
  const [settings, setSettings] = useState<LLMSettings | undefined>(undefined);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | undefined>(undefined);
  const [models, setModels] = useState<string[]>([]);

  const changeProvider = (next: string) => {
    setProvider(next);
    // Returning to the saved provider restores what was saved; moving to any
    // other clears the field, which the placeholder then reads as that
    // provider's default. Carrying the old id over is how `mistral-medium-3-5`
    // ended up sitting under a selected `ollama`.
    setModel(next === settings?.provider ? settings.model : '');
    // The list came from testing the previous provider and does not describe
    // this one.
    setModels([]);
    setMessage(undefined);
  };

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

  // Derived from the dropdown rather than the stored row, because the whole
  // point of the form is to change providers — gating on what is already saved
  // is what made Ollama unreachable once a cloud key had been stored.
  const needsKey = !(settings?.keyless_providers ?? []).includes(provider);
  // The toggles act on what is saved, so they follow the saved provider.
  const savedUsable = settings ? settings.configured || !settings.requires_key : false;

  if (!settings) {
    // A shimmer at the loaded card's footprint, matching the rest of the app —
    // a bare spinner leaves the page height jumping when the data lands.
    return <div className="surface shimmer h-96" />;
  }

  const handleTest = async () => {
    if (needsKey && !apiKey) {
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
        use_for_notes: overrides.use_for_notes ?? settings.use_for_notes,
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

  // What is serving right now, which is the question the card exists to answer
  // and which nothing on it used to state.
  const activeSummary = savedUsable
    ? `${settings.provider}${settings.model ? ` · ${settings.model}` : ' · default model'}`
    : 'Server default';

  return (
    <ProfileCard
      title="AI Provider"
      icon={Bot}
      action={
        <span className="truncate font-mono text-xs text-fg-muted" title={activeSummary}>
          {activeSummary}
        </span>
      }
    >
      <div className="space-y-5">
        {!settings.encryption_available && needsKey && (
          <div className="flex items-start gap-2 rounded-md border border-warn bg-warn-bg p-3 text-base text-warn">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              <code>LLM_KEY_ENCRYPTION_SECRET</code> is not set on the server, so your own key
              cannot be stored.
            </span>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="block">
            <span className="label mb-1.5 block">Provider</span>
            <select
              value={provider}
              onChange={(e) => changeProvider(e.target.value)}
              className={INPUT_CLASS}
            >
              {settings.supported_providers.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label mb-1.5 block">Model</span>
            <input
              list="llm-model-options"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={settings.provider_defaults[provider] || 'model id required'}
              className={`${INPUT_CLASS} font-mono`}
            />
            <datalist id="llm-model-options">
              {models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <p className="mt-1 text-xs text-fg-subtle">
              {settings.provider_defaults[provider]
                ? 'Leave blank for the default shown.'
                : 'This provider has no default — a model id is required.'}
            </p>
          </label>
        </div>

        {needsKey ? (
          <label className="block">
            <span className="label mb-1.5 block">
              API key
              {settings.configured && ` — saved …${settings.key_hint}`}
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                settings.configured ? 'Enter a new key to replace it' : 'Paste your API key'
              }
              autoComplete="off"
              className={`${INPUT_CLASS} font-mono`}
            />
          </label>
        ) : (
          <p className="text-base text-fg-muted">
            <code className="text-fg">{provider}</code> runs on this machine and takes no API key.
          </p>
        )}

        <div>
          <p className="label mb-1">{needsKey ? 'Use my key for' : 'Use this provider for'}</p>
          <div className="divide-y divide-line border-y border-line">
            {FEATURES.map(({ key, label, hint }) => {
              const on = settings[key];
              return (
                <div key={key} className="flex items-center justify-between gap-4 py-2.5">
                  <div className="min-w-0">
                    <p className="text-base text-fg">{label}</p>
                    <p className="mt-0.5 text-xs text-fg-subtle">{hint}</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={on}
                    aria-label={label}
                    disabled={busy || !savedUsable}
                    onClick={() => void save({ [key]: !on })}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40 ${
                      on ? 'bg-accent' : 'border border-line bg-surface-2'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                        on ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
                      }`}
                    />
                  </button>
                </div>
              );
            })}
          </div>
          <p className="mt-2.5 text-xs text-fg-subtle">
            What is left runs with no reader behind it and stays on the server provider: the
            two-minute news scan, the BIST radar voice pass and symbol detection. Notes are cached
            per set of facts, so the first reader through writes the copy everyone sees.
          </p>
        </div>

        {message && (
          <p
            className={`flex items-start gap-1.5 text-sm ${message.ok ? 'text-up' : 'text-down'}`}
            role="status"
          >
            {message.ok ? (
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            ) : (
              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            )}
            {message.text}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleTest()}
            className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-base text-fg-muted transition-colors hover:text-fg disabled:opacity-40"
          >
            Test
          </button>
          <button
            type="button"
            disabled={busy || (needsKey && !settings.encryption_available)}
            onClick={() => void save()}
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save
          </button>
          {settings.configured && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleDelete()}
              className="ml-auto flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-down hover:text-down disabled:opacity-40"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove key
            </button>
          )}
        </div>
      </div>
    </ProfileCard>
  );
}
