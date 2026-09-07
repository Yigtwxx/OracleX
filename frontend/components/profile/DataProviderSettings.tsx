'use client';

import { AlertTriangle, CheckCircle2, Database, ExternalLink, XCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  deleteDataProviderKey,
  getDataProviderSettings,
  updateDataProviderKey,
  type DataProviderSetting,
  type DataProviderSettings as Settings,
} from '@/lib/api';

import ProfileCard from './ProfileCard';

// Same string as AIProviderSettings, and copied for the same reason recorded
// there: `components/ui/` has no Input primitive, and importing the Alarms one
// would couple Profile to Alarms.
const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg transition-colors placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-50';

/** What is carrying this upstream right now — the card's first question. */
const SOURCE_LABEL: Record<DataProviderSetting['source'], string> = {
  user: 'Your key',
  server: 'Server key',
  none: 'Not configured',
};

const SOURCE_CLASS: Record<DataProviderSetting['source'], string> = {
  user: 'text-up',
  server: 'text-fg-muted',
  none: 'text-warn',
};

/**
 * Per-reader keys for the optional market-data upstreams.
 *
 * Deliberately one row per provider rather than a single form: the keys are
 * unrelated, and saving one must never touch another. Each row owns its own
 * input and its own busy state for the same reason.
 */
export default function DataProviderSettings() {
  const [settings, setSettings] = useState<Settings | undefined>(undefined);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      setSettings(await getDataProviderSettings());
    } catch {
      setMessage({ ok: false, text: 'Could not load data provider settings.' });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!settings) {
    return <div className="surface shimmer h-96" />;
  }

  const handleSave = async (provider: string) => {
    const key = (drafts[provider] ?? '').trim();
    if (!key) {
      setMessage({ ok: false, text: 'Enter a key first.' });
      return;
    }

    setBusy(provider);
    setMessage(undefined);
    try {
      setSettings(await updateDataProviderKey(provider, key));
      // Clearing the box is what makes the saved state legible: the row then
      // shows the hint, and the placeholder says a new key would replace it.
      setDrafts((prev) => ({ ...prev, [provider]: '' }));
      setMessage({ ok: true, text: 'Saved. New requests will use your key.' });
    } catch (error) {
      setMessage({
        ok: false,
        text: error instanceof Error ? error.message : 'Could not save that key.',
      });
    } finally {
      setBusy('');
    }
  };

  const handleDelete = async (provider: string) => {
    setBusy(provider);
    setMessage(undefined);
    try {
      setSettings(await deleteDataProviderKey(provider));
      setDrafts((prev) => ({ ...prev, [provider]: '' }));
      setMessage({ ok: true, text: 'Removed — the server key will be used, if there is one.' });
    } catch {
      setMessage({ ok: false, text: 'Could not remove that key.' });
    } finally {
      setBusy('');
    }
  };

  const editable = settings.providers.filter((p) => p.editable);
  const encryptionMissing = !settings.encryption_available && editable.length > 0;

  return (
    <ProfileCard title="Data Providers" icon={Database}>
      <div className="space-y-5">
        <p className="text-base text-fg-muted">
          Optional upstreams. Every board works without them — these keys only add data: real
          returns instead of nominal, years of open interest instead of thirty days. A key you save
          here is used for your own requests and is stored encrypted.
        </p>

        {encryptionMissing && (
          <div className="flex items-start gap-2 rounded-md border border-warn bg-warn-bg p-3 text-base text-warn">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              <code>LLM_KEY_ENCRYPTION_SECRET</code> is not set on the server, so your own keys
              cannot be stored.
            </span>
          </div>
        )}

        <div className="space-y-3">
          {settings.providers.map((provider) => (
            <div key={provider.provider} className="rounded-md border border-line p-3">
              <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-base font-semibold text-fg">{provider.label}</span>
                <span className={`text-sm ${SOURCE_CLASS[provider.source]}`}>
                  {SOURCE_LABEL[provider.source]}
                  {provider.source === 'user' && provider.key_hint && ` …${provider.key_hint}`}
                </span>
                <a
                  href={provider.signup_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto flex items-center gap-1 text-sm text-fg-muted transition-colors hover:text-fg"
                >
                  Get a key
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>

              <p className="mb-2.5 text-sm text-fg-subtle">{provider.benefit}</p>

              {provider.editable ? (
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="password"
                    value={drafts[provider.provider] ?? ''}
                    onChange={(e) =>
                      setDrafts((prev) => ({ ...prev, [provider.provider]: e.target.value }))
                    }
                    placeholder={
                      provider.user_configured
                        ? 'Enter a new key to replace it'
                        : provider.placeholder
                    }
                    autoComplete="off"
                    aria-label={`${provider.label} API key`}
                    disabled={!settings.encryption_available}
                    className={`${INPUT_CLASS} ${'min-w-48 flex-1 font-mono'}`}
                  />
                  <button
                    onClick={() => void handleSave(provider.provider)}
                    disabled={busy !== '' || !settings.encryption_available}
                    className="rounded-md bg-accent px-3 py-1.5 text-base text-white hover:opacity-90 disabled:opacity-40"
                  >
                    {busy === provider.provider ? 'Saving…' : 'Save'}
                  </button>
                  {provider.user_configured && (
                    <button
                      onClick={() => void handleDelete(provider.provider)}
                      disabled={busy !== ''}
                      className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-base text-fg-muted hover:text-fg disabled:opacity-40"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ) : (
                // Server-scoped: the upstream feeds a shared artefact rebuilt on
                // a schedule, so there is no request of this reader's to attach
                // a key to. Naming the variable is the useful thing to say.
                <p className="text-sm text-fg-subtle">
                  Server setting — whoever runs this install sets{' '}
                  <code className="text-fg-muted">{provider.env_var}</code> in the environment.
                </p>
              )}
            </div>
          ))}
        </div>

        {message && (
          <p
            role="status"
            className={`flex items-center gap-1.5 text-base ${message.ok ? 'text-up' : 'text-down'}`}
          >
            {message.ok ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
            ) : (
              <XCircle className="h-3.5 w-3.5 shrink-0" />
            )}
            {message.text}
          </p>
        )}
      </div>
    </ProfileCard>
  );
}
