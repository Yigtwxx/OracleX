'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Loader2, Send, Server } from 'lucide-react';
import { ApiError } from '@/lib/api';
import {
  clearSmtpSettings,
  fetchSmtpSettings,
  saveSmtpSettings,
  testSmtpRelay,
  type SmtpSettings,
  type SmtpSettingsPatch,
} from '@/lib/alarms/email';
import { Field, INPUT_CLASS, PRIMARY_BUTTON_CLASS, Segmented } from './controls';

/**
 * The relay, editable in place.
 *
 * Only an admin ever sees this — the four routes behind it are guarded by
 * `require_admin`, and the parent hides the whole section otherwise. What it
 * configures is one deployment-wide account, not a per-user preference, which
 * is why it lives here rather than in a profile page: the person setting the
 * relay up and the person about to confirm an address are usually the same one,
 * and sending them to a different screen to do half the job is the friction the
 * feature exists to remove.
 *
 * Two decisions the layout makes on purpose:
 *
 * A preset row for the common providers, because the failure everybody hits is
 * a wrong port/TLS combination, and picking "Gmail" removes three chances to
 * get it wrong. Custom stays available and nothing is locked.
 *
 * The password field is never populated. The backend does not return it, so a
 * blank box means "keep the stored one" and the label says so — the alternative,
 * a fake row of bullets, invites an admin to think they can read it back.
 */

interface Preset {
  id: string;
  label: string;
  host: string;
  port: number;
  ssl: boolean;
  starttls: boolean;
  /** Named where a provider refuses the account password outright. */
  note?: string;
}

const PRESETS: Preset[] = [
  {
    id: 'gmail',
    label: 'Gmail',
    host: 'smtp.gmail.com',
    port: 587,
    ssl: false,
    starttls: true,
    note: 'Gmail refuses your account password. Create an app password under Google Account → Security → 2-Step Verification → App passwords, and paste the 16 characters without spaces.',
  },
  {
    id: 'outlook',
    label: 'Outlook',
    host: 'smtp-mail.outlook.com',
    port: 587,
    ssl: false,
    starttls: true,
  },
  { id: 'yandex', label: 'Yandex', host: 'smtp.yandex.com', port: 465, ssl: true, starttls: false },
  { id: 'custom', label: 'Custom', host: '', port: 587, ssl: false, starttls: true },
];

interface Draft {
  host: string;
  port: string;
  user: string;
  password: string;
  fromAddress: string;
  fromName: string;
  replyTo: string;
  ssl: boolean;
  starttls: boolean;
}

function draftFrom(settings: SmtpSettings): Draft {
  return {
    host: settings.host,
    port: String(settings.port),
    user: settings.user,
    password: '',
    fromAddress: settings.fromAddress,
    fromName: settings.fromName,
    replyTo: settings.replyTo,
    ssl: settings.ssl,
    starttls: settings.starttls,
  };
}

export default function SmtpSettingsForm({ onChanged }: { onChanged: () => void }) {
  const [settings, setSettings] = useState<SmtpSettings | undefined>();
  const [draft, setDraft] = useState<Draft | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'save' | 'test' | 'clear' | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [notice, setNotice] = useState<string | undefined>();
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchSmtpSettings()
      .then((loaded) => {
        if (cancelled) return;
        setSettings(loaded);
        setDraft(draftFrom(loaded));
      })
      .catch((caught) => {
        if (!cancelled) setError(messageOf(caught, 'The relay settings could not be read.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Which preset the current host matches, so reopening the panel shows the
  // provider rather than defaulting to "Custom" on settings it recognises.
  const activePreset =
    PRESETS.find((preset) => preset.host && preset.host === draft?.host.trim())?.id ?? 'custom';
  const presetNote = PRESETS.find((preset) => preset.id === activePreset)?.note;

  function applyPreset(id: string) {
    const preset = PRESETS.find((entry) => entry.id === id);
    if (!preset || !draft) return;
    setDraft({
      ...draft,
      // "Custom" clears nothing: it is how an admin edits a host by hand after
      // starting from a preset, and wiping the field would undo their typing.
      host: preset.id === 'custom' ? draft.host : preset.host,
      port: preset.id === 'custom' ? draft.port : String(preset.port),
      ssl: preset.id === 'custom' ? draft.ssl : preset.ssl,
      starttls: preset.id === 'custom' ? draft.starttls : preset.starttls,
    });
  }

  function update(patch: Partial<Draft>) {
    if (!draft) return;
    setDraft({ ...draft, ...patch });
  }

  async function handleSave() {
    if (!draft) return;
    setError(undefined);
    setNotice(undefined);
    setBusy('save');
    try {
      const patch: SmtpSettingsPatch = {
        host: draft.host.trim(),
        port: Number(draft.port) || 587,
        user: draft.user.trim(),
        ssl: draft.ssl,
        starttls: draft.starttls,
        fromAddress: draft.fromAddress.trim(),
        fromName: draft.fromName.trim(),
        replyTo: draft.replyTo.trim(),
      };
      // Only sent when something was typed. An empty string would delete the
      // stored password, which is not what an untouched field means.
      if (draft.password) patch.password = draft.password;

      const saved = await saveSmtpSettings(patch);
      setSettings(saved);
      setDraft(draftFrom(saved));
      setNotice('Relay saved.');
      onChanged();
    } catch (caught) {
      setError(messageOf(caught, 'The relay settings could not be saved.'));
    } finally {
      setBusy(undefined);
    }
  }

  async function handleTest() {
    setError(undefined);
    setNotice(undefined);
    setBusy('test');
    try {
      await testSmtpRelay();
      setNotice('Test message handed to the relay. Check the inbox of the admin address.');
    } catch (caught) {
      setError(messageOf(caught, 'The relay refused the test message.'));
    } finally {
      setBusy(undefined);
    }
  }

  async function handleClear() {
    setError(undefined);
    setNotice(undefined);
    setBusy('clear');
    try {
      const cleared = await clearSmtpSettings();
      setSettings(cleared);
      setDraft(draftFrom(cleared));
      setNotice('Overrides removed. Back to whatever backend/.env says.');
      onChanged();
    } catch (caught) {
      setError(messageOf(caught, 'The overrides could not be removed.'));
    } finally {
      setBusy(undefined);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-base text-fg-subtle">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Reading relay settings…
      </div>
    );
  }

  if (!draft || !settings) {
    return (
      <Notice tone="down" icon={AlertTriangle}>
        {error ?? 'The relay settings could not be read.'}
      </Notice>
    );
  }

  return (
    <section className="space-y-4 rounded-lg border border-line bg-surface-2 p-4">
      <header className="flex items-start gap-3">
        <Server className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" />
        <div className="min-w-0 flex-1">
          <h3 className="text-md text-fg">SMTP relay</h3>
          <p className="mt-0.5 text-xs text-fg-subtle">
            {settings.configured
              ? `Sending as ${settings.sender} · ${SOURCE_LABEL[settings.source]}`
              : 'Nothing configured yet. Alarm emails stay off until this works.'}
          </p>
        </div>
      </header>

      <Field label="Provider">
        <Segmented
          ariaLabel="Provider"
          options={PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))}
          value={activePreset}
          onChange={applyPreset}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-[1fr_7rem]">
        <Field label="Host">
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            placeholder="smtp.example.com"
            value={draft.host}
            onChange={(e) => update({ host: e.target.value })}
            className={INPUT_CLASS}
          />
        </Field>
        <Field label="Port">
          <input
            type="text"
            inputMode="numeric"
            value={draft.port}
            onChange={(e) => update({ port: e.target.value.replace(/\D/g, '').slice(0, 5) })}
            className={`${INPUT_CLASS} font-mono`}
          />
        </Field>
      </div>

      <Field label="Account">
        <input
          type="email"
          autoComplete="off"
          placeholder="alerts@example.com"
          value={draft.user}
          onChange={(e) => update({ user: e.target.value })}
          className={INPUT_CLASS}
        />
      </Field>

      <Field
        label="Password"
        hint={
          settings.hasPassword
            ? 'A password is stored. Leave blank to keep it.'
            : 'Stored encrypted; never returned to this page.'
        }
      >
        <input
          type="password"
          // Not `current-password`: a browser autofilling the admin's own login
          // into a relay credential field is a confusing way to lose an evening.
          autoComplete="new-password"
          placeholder={settings.hasPassword ? '••••••••  (unchanged)' : ''}
          value={draft.password}
          onChange={(e) => update({ password: e.target.value })}
          className={INPUT_CLASS}
        />
      </Field>

      {presetNote && (
        <Notice tone="warn" icon={AlertTriangle}>
          {presetNote}
        </Notice>
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((open) => !open)}
          aria-expanded={showAdvanced}
          className="flex items-center gap-1.5 text-base text-fg-muted transition-colors hover:text-fg"
        >
          <ChevronDown
            className={`h-3.5 w-3.5 transition-transform ${showAdvanced ? 'rotate-180' : ''}`}
          />
          Sender and encryption
        </button>

        {showAdvanced && (
          <div className="mt-4 space-y-4">
            <Field
              label="From address"
              hint="Leave blank to send as the account above — which is what keeps SPF and DKIM aligned and the message out of spam. Set this only if your relay allows another sender."
            >
              <input
                type="email"
                autoComplete="off"
                placeholder={draft.user || 'alerts@example.com'}
                value={draft.fromAddress}
                onChange={(e) => update({ fromAddress: e.target.value })}
                className={INPUT_CLASS}
              />
            </Field>

            <Field label="From name">
              <input
                type="text"
                placeholder="Oracle-X"
                value={draft.fromName}
                onChange={(e) => update({ fromName: e.target.value })}
                className={INPUT_CLASS}
              />
            </Field>

            <Field label="Reply-To" hint="Blank means replies go back to the From address.">
              <input
                type="email"
                autoComplete="off"
                value={draft.replyTo}
                onChange={(e) => update({ replyTo: e.target.value })}
                className={INPUT_CLASS}
              />
            </Field>

            <Field
              label="Encryption"
              hint="STARTTLS upgrades a plain connection and is what port 587 expects; SSL/TLS is encrypted from the first byte and is what port 465 expects."
            >
              <Segmented
                ariaLabel="Encryption"
                options={[
                  { value: 'starttls', label: 'STARTTLS' },
                  { value: 'ssl', label: 'SSL/TLS' },
                ]}
                value={draft.ssl ? 'ssl' : 'starttls'}
                onChange={(value) =>
                  update({ ssl: value === 'ssl', starttls: value === 'starttls' })
                }
              />
            </Field>
          </div>
        )}
      </div>

      {error && (
        <Notice tone="down" icon={AlertTriangle}>
          {error}
        </Notice>
      )}
      {notice && !error && (
        <Notice tone="up" icon={Check}>
          {notice}
        </Notice>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={busy !== undefined || draft.host.trim().length === 0}
          className={PRIMARY_BUTTON_CLASS}
        >
          {busy === 'save' ? 'Saving…' : 'Save relay'}
        </button>

        <button
          type="button"
          onClick={() => void handleTest()}
          disabled={busy !== undefined || !settings.configured}
          title={settings.configured ? undefined : 'Save a working relay first'}
          className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
        >
          {busy === 'test' ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
          Send test
        </button>

        {settings.source === 'panel' && (
          <button
            type="button"
            onClick={() => void handleClear()}
            disabled={busy !== undefined}
            className="ml-auto px-2 py-1.5 text-base text-fg-subtle transition-colors hover:text-down disabled:opacity-50"
          >
            {busy === 'clear' ? 'Removing…' : 'Remove overrides'}
          </button>
        )}
      </div>
    </section>
  );
}

const SOURCE_LABEL: Record<SmtpSettings['source'], string> = {
  panel: 'set here',
  env: 'from backend/.env',
  none: 'not configured',
};

const NOTICE_TONES = {
  up: 'border-up/30 bg-up-bg text-up',
  down: 'border-down/30 bg-down-bg text-down',
  warn: 'border-warn/30 bg-warn-bg text-warn',
} as const;

function Notice({
  tone,
  icon: Icon,
  children,
}: {
  tone: keyof typeof NOTICE_TONES;
  icon: typeof AlertTriangle;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2.5 ${NOTICE_TONES[tone]}`}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <p className="text-base leading-relaxed text-fg-muted">{children}</p>
    </div>
  );
}

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  return fallback;
}
