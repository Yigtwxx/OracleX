'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, Check, Loader2, Mail, Trash2 } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useIsAdmin } from '@/hooks/useAdmin';
import { ApiError } from '@/lib/api';
import {
  confirmAlarmEmailCode,
  fetchAlarmEmailStatus,
  requestAlarmEmailCode,
  sendAlarmEmail,
} from '@/lib/alarms/email';
import { Field, INPUT_CLASS, PRIMARY_BUTTON_CLASS } from './controls';
import SmtpSettingsForm from './SmtpSettingsForm';

/**
 * The mail channel's settings pane.
 *
 * A three-step flow — type an address, type the code it received, done — drawn
 * as one screen at a time rather than as a form with a disabled half. The step
 * is derived from state that already exists (is there a stored address? is there
 * a pending one?) rather than from a `step` variable, so there is no way to be
 * on step 2 with no address to confirm.
 *
 * The tab-open caveat is stated on the confirmed screen and not buried in a
 * tooltip. It is the one thing about this feature that will surprise someone,
 * and finding out by not receiving a mail is the worst way to learn it.
 */

const CODE_LENGTH = 6;

type Phase = 'checking' | 'unavailable' | 'idle' | 'sending' | 'awaiting-code' | 'verifying';

export default function AlarmEmailSettings() {
  const identity = useStore((state) => state.alarmEmail);
  const setAlarmEmail = useStore((state) => state.setAlarmEmail);
  // Whether the relay form is offered at all. `data` is undefined while the
  // session query is in flight and for every signed-out visitor, which is the
  // right default: the form appears once adminship is known, never before.
  const { data: session } = useIsAdmin();
  const isAdmin = session?.is_admin === true;

  const [phase, setPhase] = useState<Phase>('checking');
  const [address, setAddress] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | undefined>();
  const [notice, setNotice] = useState<string | undefined>();
  const [testing, setTesting] = useState(false);

  const codeInput = useRef<HTMLInputElement>(null);

  // Bumped after the relay form saves, to re-ask whether mail now works. A
  // counter rather than a boolean: two saves in a row must both re-run this.
  const [relayRevision, setRelayRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAlarmEmailStatus()
      .then((enabled) => {
        // Only the two states this query decides. Re-running it mid-confirmation
        // — which a relay save does — must not throw away a code the user is
        // part-way through typing.
        if (cancelled) return;
        setPhase((current) =>
          current === 'checking' || current === 'idle' || current === 'unavailable'
            ? enabled
              ? 'idle'
              : 'unavailable'
            : current
        );
      })
      .catch(() => {
        // An unreachable backend is not "this deployment cannot send mail" — but
        // from here the two are indistinguishable and the honest render is the
        // one that does not promise a working button.
        if (!cancelled) setPhase('unavailable');
      });
    return () => {
      cancelled = true;
    };
  }, [relayRevision]);

  // Moving to the code step should put the cursor in the code box. Doing it in
  // the click handler would run before the input exists.
  useEffect(() => {
    if (phase === 'awaiting-code') codeInput.current?.focus();
  }, [phase]);

  async function handleRequestCode() {
    setError(undefined);
    setNotice(undefined);
    setPhase('sending');
    try {
      await requestAlarmEmailCode(address.trim());
      setCode('');
      setPhase('awaiting-code');
    } catch (caught) {
      setError(messageOf(caught, 'The confirmation email could not be sent.'));
      setPhase('idle');
    }
  }

  async function handleConfirm() {
    setError(undefined);
    setPhase('verifying');
    try {
      const confirmed = await confirmAlarmEmailCode(address.trim(), code.trim());
      setAlarmEmail(confirmed);
      setAddress('');
      setCode('');
      setPhase('idle');
      setNotice('Address confirmed. Alarms will reach this inbox from now on.');
    } catch (caught) {
      setError(messageOf(caught, 'That code could not be confirmed.'));
      setPhase('awaiting-code');
    }
  }

  async function handleTest() {
    if (!identity) return;
    setError(undefined);
    setNotice(undefined);
    setTesting(true);
    try {
      await sendAlarmEmail(identity, {
        // A fresh id per press: the backend drops a repeat of one it already
        // delivered, and a fixed id would make the second test silently do
        // nothing while reporting success.
        eventId: `test_${Date.now()}`,
        sourceLabel: 'Price',
        subjectLine: 'BTCUSDT · Price (sample)',
        observed: '$72,450.00',
        rule: 'price rises above $70,000.00',
        firedAtLabel: new Date().toLocaleString('en-US', {
          day: 'numeric',
          month: 'long',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        }),
        tone: 'up',
        headline: 'BTCUSDT · Price rose above your $70,000.00 level.',
        lead: 'This is a sample, so the reading below is made up. A real alarm looks exactly like this.',
        threshold: '$70,000.00',
        distance: '+3.50%',
      });
      setNotice('Sample email sent. Check the spam folder if it does not arrive.');
    } catch (caught) {
      setError(messageOf(caught, 'The sample email could not be sent.'));
    } finally {
      setTesting(false);
    }
  }

  function handleRemove() {
    setAlarmEmail(undefined);
    setNotice(undefined);
    setError(undefined);
    setPhase('idle');
  }

  if (phase === 'checking') {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-4 h-4 text-fg-subtle animate-spin" aria-label="Loading" />
      </div>
    );
  }

  if (phase === 'unavailable') {
    return (
      <div className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar px-5 py-5">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <Callout tone="warn" icon={AlertTriangle} title="Email alerts are off">
            {isAdmin
              ? 'No SMTP relay is configured yet. Point this at a mailbox below and alarms will start arriving by email as well. Nothing else about alarms changes.'
              : 'No SMTP relay is configured on this server, so alarms cannot be emailed. Everything else about them still works — the toast, the sound and the desktop notification all fire as usual.'}
          </Callout>
          {isAdmin && <SmtpSettingsForm onChanged={() => setRelayRevision((n) => n + 1)} />}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar px-5 py-5">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:items-start">
        <div className="space-y-5">
          {identity ? (
            <ConfirmedPanel
              address={identity.address}
              testing={testing}
              onTest={handleTest}
              onRemove={handleRemove}
            />
          ) : phase === 'awaiting-code' || phase === 'verifying' ? (
            <div className="space-y-4">
              <header className="space-y-1">
                <h2 className="text-md text-fg">Enter the code</h2>
                <p className="text-base text-fg-muted">
                  A {CODE_LENGTH}-digit code is on its way to{' '}
                  <span className="text-fg">{address.trim()}</span>. Check the spam folder if it
                  does not arrive.
                </p>
              </header>

              <Field label="Confirmation code">
                <input
                  ref={codeInput}
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={CODE_LENGTH}
                  placeholder="000000"
                  value={code}
                  // Digits only, so a code pasted with a stray space or a copied
                  // "Your code: 418302" still lands as six digits.
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && code.length === CODE_LENGTH) void handleConfirm();
                  }}
                  className={`${INPUT_CLASS} font-mono text-lg tracking-[0.4em]`}
                />
              </Field>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleConfirm()}
                  disabled={code.length !== CODE_LENGTH || phase === 'verifying'}
                  className={PRIMARY_BUTTON_CLASS}
                >
                  {phase === 'verifying' ? 'Confirming…' : 'Confirm'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPhase('idle');
                    setCode('');
                    setError(undefined);
                  }}
                  className="flex items-center gap-1.5 px-2 py-1.5 text-base text-fg-muted hover:text-fg transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  Change address
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <header className="space-y-1">
                <h2 className="text-md text-fg">Email alerts</h2>
                <p className="text-base text-fg-muted">
                  Get an email alongside the sound and the notification when an alarm fires. Nothing
                  is sent to an address until it has been confirmed.
                </p>
              </header>

              <Field label="Email address" hint="Used for alarm notifications and nothing else.">
                <input
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && looksLikeEmail(address)) void handleRequestCode();
                  }}
                  className={INPUT_CLASS}
                />
              </Field>

              <button
                type="button"
                onClick={() => void handleRequestCode()}
                disabled={!looksLikeEmail(address) || phase === 'sending'}
                className={PRIMARY_BUTTON_CLASS}
              >
                {phase === 'sending' ? 'Sending…' : 'Send confirmation code'}
              </button>
            </div>
          )}

          {error && (
            <Callout tone="down" icon={AlertTriangle} title="That did not work">
              {error}
            </Callout>
          )}
          {notice && !error && (
            <Callout tone="up" icon={Check} title="Done">
              {notice}
            </Callout>
          )}
        </div>

        {/* The relay lives in the second column rather than under a disclosure
            at the bottom. It is admin-only settings, so it must not compete with
            the confirmation form — but the pane is wide and stacking it below
            left most of that width empty while hiding the thing entirely. */}
        {isAdmin && <SmtpSettingsForm onChanged={() => setRelayRevision((n) => n + 1)} />}
      </div>
    </div>
  );
}

function ConfirmedPanel({
  address,
  testing,
  onTest,
  onRemove,
}: {
  address: string;
  testing: boolean;
  onTest: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-line bg-surface-2 px-4 py-3.5">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-up-bg">
            <Check className="h-3.5 w-3.5 text-up" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="label">Confirmed address</p>
            <p className="mt-0.5 truncate font-mono text-base text-fg">{address}</p>
          </div>
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove email address"
            title="Remove"
            className="shrink-0 rounded-md p-1.5 text-fg-muted transition-colors hover:bg-surface hover:text-down"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <button
        type="button"
        onClick={onTest}
        disabled={testing}
        className="flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
      >
        {testing ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Mail className="h-3.5 w-3.5" />
        )}
        {testing ? 'Sending…' : 'Send a sample email'}
      </button>

      <Callout tone="warn" icon={AlertTriangle} title="The tab has to stay open">
        This page is what evaluates the alarms. With the Oracle-X tab closed nothing is checked, so
        no email is sent either. Leaving it open in the background is enough.
      </Callout>
    </div>
  );
}

const CALLOUT_TONES = {
  up: 'border-up/30 bg-up-bg text-up',
  down: 'border-down/30 bg-down-bg text-down',
  warn: 'border-warn/30 bg-warn-bg text-warn',
} as const;

function Callout({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: keyof typeof CALLOUT_TONES;
  icon: typeof AlertTriangle;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-lg border px-3.5 py-3 ${CALLOUT_TONES[tone]}`}>
      <p className="flex items-center gap-1.5 text-base font-medium">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        {title}
      </p>
      {/* The body is deliberately not tinted: a whole paragraph in the accent
          colour is harder to read than the same paragraph in body ink, and the
          icon and border already carry the tone. */}
      <p className="mt-1 text-base leading-relaxed text-fg-muted">{children}</p>
    </div>
  );
}

/**
 * Enough to decide whether the button is worth enabling — not a validator.
 *
 * The real check is `services/email_guard`, which resolves the domain over DNS
 * before a code is sent. Re-implementing any part of it here would only produce
 * a second, weaker opinion that disagrees with the backend's.
 */
function looksLikeEmail(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length >= 5 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);
}

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  return fallback;
}
