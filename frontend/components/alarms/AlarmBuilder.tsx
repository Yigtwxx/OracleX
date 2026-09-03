'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Crosshair, X } from 'lucide-react';
import { useStore, type NewAlarm } from '@/store/useStore';
import { getAlarmSource } from '@/lib/alarms/registry';
import { describeAlarm, formatFieldValue } from '@/lib/alarms/describe';
import { requestNotificationPermission } from '@/lib/alarms/notify';
import { type AlarmCondition, type AlarmSourceId, type ThresholdOp } from '@/lib/alarms/types';
import { ALARM_ICONS } from './icons';
import { Chip, Field, PRIMARY_BUTTON_CLASS, Segmented, Select, INPUT_CLASS } from './controls';
import { useSourceReading } from './useSourceReading';

const MINUTE = 60 * 1000;

const COOLDOWN_CHOICES = [
  { value: String(MINUTE), label: '1 minute' },
  { value: String(5 * MINUTE), label: '5 minutes' },
  { value: String(15 * MINUTE), label: '15 minutes' },
  { value: String(60 * MINUTE), label: '1 hour' },
  { value: String(4 * 60 * MINUTE), label: '4 hours' },
];

const LEAD_CHOICES = [
  { value: '5', label: '5 minutes' },
  { value: '15', label: '15 minutes' },
  { value: '30', label: '30 minutes' },
  { value: '60', label: '1 hour' },
  { value: '1440', label: '1 day' },
];

/**
 * Offsets from the live reading, one click each.
 *
 * The hardest part of setting a threshold was arithmetic: the builder showed
 * the current price and an empty box, and left the user to work out what "five
 * percent above $67,412.38" is. These do it. The sign also picks the direction,
 * because a level above the current reading can only sensibly mean "tell me
 * when it gets there".
 */
const OFFSET_STEPS = [-10, -5, -2, 2, 5, 10] as const;

/** Which condition shapes this source offers, in the order they are presented. */
function conditionChoices(sourceId: AlarmSourceId) {
  const source = getAlarmSource(sourceId);
  const choices: { value: string; label: string }[] = [];
  if (source.thresholdFields.length > 0) choices.push({ value: 'threshold', label: 'Threshold' });
  if (source.stateField) choices.push({ value: 'state', label: 'Status' });
  if (source.supportsKeyword) choices.push({ value: 'keyword', label: 'Keyword' });
  if (source.supportsCountdown) choices.push({ value: 'countdown', label: 'Countdown' });
  return choices;
}

export default function AlarmBuilder({
  sourceId,
  initialParams,
  onCreated,
}: {
  sourceId: AlarmSourceId;
  initialParams: Record<string, string>;
  onCreated: () => void;
}) {
  const source = getAlarmSource(sourceId);
  const addAlarm = useStore((state) => state.addAlarm);
  const Icon = ALARM_ICONS[source.icon];

  const [params, setParams] = useState<Record<string, string>>(initialParams);
  const [condition, setCondition] = useState<AlarmCondition>(source.defaultCondition);
  const [thresholdText, setThresholdText] = useState(
    source.defaultCondition.kind === 'threshold' ? String(source.defaultCondition.value) : ''
  );
  const [terms, setTerms] = useState<string[]>([]);
  const [termDraft, setTermDraft] = useState('');
  const [repeat, setRepeat] = useState<'once' | 'always'>('once');
  const [cooldownMs, setCooldownMs] = useState(source.defaultCooldownMs);
  const [showMore, setShowMore] = useState(false);

  // Whether the threshold still holds a value nobody chose. Seeding it from the
  // live reading is only right until the user expresses an opinion; after that a
  // late-arriving price must not overwrite what they typed.
  const thresholdUntouched = useRef(true);

  // Switching source resets the form. Carrying a threshold from a price alarm
  // into a Fear & Greed one would preload a number that means nothing there.
  useEffect(() => {
    setParams(initialParams);
    setCondition(source.defaultCondition);
    setThresholdText(
      source.defaultCondition.kind === 'threshold' ? String(source.defaultCondition.value) : ''
    );
    setTerms([]);
    setTermDraft('');
    setRepeat('once');
    setCooldownMs(source.defaultCooldownMs);
    setShowMore(false);
    thresholdUntouched.current = true;
  }, [sourceId, source.defaultCondition, source.defaultCooldownMs, initialParams]);

  const reading = useSourceReading(sourceId, params, true);

  const activeField =
    condition.kind === 'threshold'
      ? source.thresholdFields.find((f) => f.key === condition.field)
      : undefined;

  /** The live number for the field being thresholded, when there is one. */
  const currentValue = useMemo(() => {
    if (condition.kind !== 'threshold') return undefined;
    const raw = reading.data?.values[condition.field];
    return typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined;
  }, [condition, reading.data]);

  // A source whose registry default is 0 has no meaningful default — a price
  // alarm cannot know its own scale before the symbol is known. Seed those from
  // the live reading rather than making the user delete a zero first.
  useEffect(() => {
    if (condition.kind !== 'threshold' || !thresholdUntouched.current) return;
    if (currentValue === undefined || condition.value !== 0) return;
    const seeded = roundTo(currentValue * 1.05, activeField?.decimals ?? 2);
    setThresholdText(String(seeded));
    setCondition({ ...condition, value: seeded, op: 'above' });
  }, [currentValue, condition, activeField]);

  const draft: NewAlarm = useMemo(
    () => ({ sourceId, params, condition, repeat, cooldownMs, enabled: true }),
    [sourceId, params, condition, repeat, cooldownMs]
  );

  const previewAlarm = {
    ...draft,
    id: 'preview',
    createdAt: '',
    lastTriggeredAt: undefined,
    triggerCount: 0,
    seenKeys: [],
    armed: true,
  };

  const missingRequired = source.params.filter(
    (spec) => spec.required && !params[spec.key]?.trim()
  );
  const invalidThreshold =
    condition.kind === 'threshold' && !Number.isFinite(Number(thresholdText.replace(',', '.')));
  const emptyKeywords = condition.kind === 'keyword' && terms.length === 0;
  const emptyStates = condition.kind === 'state' && condition.states.length === 0;
  const canSubmit =
    missingRequired.length === 0 && !invalidThreshold && !emptyKeywords && !emptyStates;

  // How far the level sits from the reading, and whether it is already met.
  // Both were previously left for the user to work out from two numbers on
  // opposite sides of the panel.
  const gap =
    condition.kind === 'threshold' && currentValue !== undefined && currentValue !== 0
      ? ((condition.value - currentValue) / Math.abs(currentValue)) * 100
      : undefined;
  const alreadyTrue =
    condition.kind === 'threshold' && currentValue !== undefined
      ? condition.op === 'above'
        ? currentValue > condition.value
        : currentValue < condition.value
      : false;

  function setThreshold(text: string) {
    thresholdUntouched.current = false;
    setThresholdText(text);
    const parsed = Number(text.replace(',', '.'));
    if (condition.kind === 'threshold' && Number.isFinite(parsed)) {
      setCondition({ ...condition, value: parsed });
    }
  }

  /** One offset chip: sets the level and the direction it implies. */
  function applyOffset(percent: number) {
    if (condition.kind !== 'threshold' || currentValue === undefined) return;
    const value = roundTo(currentValue * (1 + percent / 100), activeField?.decimals ?? 2);
    thresholdUntouched.current = false;
    setThresholdText(String(value));
    setCondition({ ...condition, value, op: percent >= 0 ? 'above' : 'below' });
  }

  function useCurrent() {
    if (condition.kind !== 'threshold' || currentValue === undefined) return;
    const value = roundTo(currentValue, activeField?.decimals ?? 2);
    thresholdUntouched.current = false;
    setThresholdText(String(value));
    setCondition({ ...condition, value });
  }

  function addTerm(raw: string) {
    const cleaned = raw.trim();
    if (!cleaned) return;
    // Splitting on commas keeps the old syntax working for anyone who learned
    // it — it just is not required any more.
    const next = Array.from(new Set([...terms, ...cleaned.split(',').map((t) => t.trim())])).filter(
      (t) => t.length > 0
    );
    setTerms(next);
    setTermDraft('');
    if (condition.kind === 'keyword') setCondition({ ...condition, terms: next });
  }

  function removeTerm(term: string) {
    const next = terms.filter((t) => t !== term);
    setTerms(next);
    if (condition.kind === 'keyword') setCondition({ ...condition, terms: next });
  }

  function switchKind(kind: string) {
    const first = source.thresholdFields[0];
    if (kind === 'threshold' && first) {
      const value = Number(thresholdText.replace(',', '.'));
      setCondition({
        kind: 'threshold',
        field: first.key,
        op: 'above',
        value: Number.isFinite(value) ? value : 0,
      });
    } else if (kind === 'state' && source.stateField) {
      setCondition({ kind: 'state', field: source.stateField.key, states: [] });
    } else if (kind === 'keyword') {
      setCondition({ kind: 'keyword', terms, matchIn: 'both' });
    } else if (kind === 'countdown') {
      setCondition({ kind: 'countdown', leadMinutes: 15 });
    }
  }

  function submit() {
    if (!canSubmit) return;
    addAlarm(draft);
    // Ask only now: a permission prompt on page load, before the user has shown
    // any interest in alarms, is the one people reflexively deny.
    requestNotificationPermission();
    onCreated();
  }

  const choices = conditionChoices(sourceId);
  const readingText = reading.isLoading
    ? '…'
    : reading.isError
      ? 'unavailable'
      : (reading.data?.display ?? 'no reading');

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-line px-5 py-4">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-fg-muted" />
          <h4 className="text-md font-semibold text-fg">{source.label}</h4>
        </div>
        <p className="mt-1 text-xs text-fg-subtle">{source.description}</p>
      </div>

      {/* Two columns from `lg` up: the form on the left, and everything that
          answers "is this what I meant?" — the live reading, the sentence, the
          warning — beside it rather than at the bottom of a scroll. */}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden custom-scrollbar">
        <div className="grid gap-6 px-5 py-4 lg:grid-cols-[minmax(0,1fr)_19rem]">
          <div className="min-w-0 space-y-5">
            {source.params.map((spec) => (
              <Field key={spec.key} label={spec.label} hint={spec.hint}>
                {spec.kind === 'select' ? (
                  <Select
                    ariaLabel={spec.label}
                    value={params[spec.key] ?? ''}
                    options={spec.options ?? []}
                    onChange={(value) => setParams({ ...params, [spec.key]: value })}
                  />
                ) : (
                  <input
                    type="text"
                    className={INPUT_CLASS}
                    placeholder={spec.placeholder}
                    value={params[spec.key] ?? ''}
                    onChange={(e) =>
                      setParams({
                        ...params,
                        [spec.key]:
                          spec.kind === 'symbol' ? e.target.value.toUpperCase() : e.target.value,
                      })
                    }
                  />
                )}
              </Field>
            ))}

            {choices.length > 1 && (
              <Field label="Condition">
                <Segmented
                  ariaLabel="Condition"
                  options={choices}
                  value={condition.kind}
                  onChange={switchKind}
                />
              </Field>
            )}

            {condition.kind === 'threshold' && (
              <>
                {source.thresholdFields.length > 1 && (
                  <Field label="Field">
                    <Segmented
                      ariaLabel="Field"
                      options={source.thresholdFields.map((f) => ({
                        value: f.key,
                        label: f.label,
                      }))}
                      value={condition.field}
                      onChange={(field) => setCondition({ ...condition, field })}
                    />
                  </Field>
                )}

                <Field label="Notify me when it">
                  <Segmented
                    ariaLabel="Direction"
                    options={[
                      { value: 'above', label: 'Rises above' },
                      { value: 'below', label: 'Falls below' },
                    ]}
                    value={condition.op}
                    onChange={(op) => setCondition({ ...condition, op: op as ThresholdOp })}
                  />
                </Field>

                <Field label="Level">
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label="Level"
                      className={`${INPUT_CLASS} font-mono`}
                      value={thresholdText}
                      onChange={(e) => setThreshold(e.target.value)}
                    />
                    <span className="min-w-[2.5rem] shrink-0 text-base text-fg-muted">
                      {activeField?.unit || activeField?.prefix || ''}
                    </span>
                  </div>

                  {currentValue !== undefined && (
                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        onClick={useCurrent}
                        className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
                      >
                        <Crosshair className="h-3 w-3" />
                        Current
                      </button>
                      {OFFSET_STEPS.map((step) => (
                        <button
                          key={step}
                          type="button"
                          onClick={() => applyOffset(step)}
                          className="rounded-md border border-line px-2 py-1 font-mono text-xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
                        >
                          {step > 0 ? `+${step}%` : `${step}%`}
                        </button>
                      ))}
                    </div>
                  )}

                  {gap !== undefined && (
                    <p className="mt-2 text-xs text-fg-subtle">
                      {Math.abs(gap) < 0.005
                        ? 'Level is the current reading.'
                        : `${Math.abs(gap).toFixed(2)}% ${gap > 0 ? 'above' : 'below'} the current reading.`}
                    </p>
                  )}
                </Field>
              </>
            )}

            {condition.kind === 'state' && source.stateField && (
              <Field label={source.stateField.label} hint="More than one can be selected.">
                <div className="flex flex-wrap gap-1.5">
                  {source.stateField.options.map((option) => (
                    <Chip
                      key={option.value}
                      active={condition.states.includes(option.value)}
                      onClick={() =>
                        setCondition({
                          ...condition,
                          states: condition.states.includes(option.value)
                            ? condition.states.filter((s) => s !== option.value)
                            : [...condition.states, option.value],
                        })
                      }
                    >
                      {option.label}
                    </Chip>
                  ))}
                </div>
              </Field>
            )}

            {condition.kind === 'keyword' && (
              <>
                <Field label="Keywords" hint="Type a word and press Enter. Case-insensitive.">
                  {/* Chips rather than a comma-separated string: the old field
                      gave no feedback on what had actually been parsed, so a
                      stray comma silently produced an empty term matching
                      nothing. */}
                  <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2 py-1.5 focus-within:border-accent">
                    {terms.map((term) => (
                      <span
                        key={term}
                        className="flex items-center gap-1 rounded bg-surface px-1.5 py-0.5 text-base text-fg"
                      >
                        {term}
                        <button
                          type="button"
                          onClick={() => removeTerm(term)}
                          aria-label={`Remove ${term}`}
                          className="text-fg-subtle transition-colors hover:text-down"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    <input
                      type="text"
                      aria-label="Add a keyword"
                      placeholder={terms.length === 0 ? 'fed, cpi, rate cut' : ''}
                      value={termDraft}
                      onChange={(e) => setTermDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ',') {
                          e.preventDefault();
                          addTerm(termDraft);
                        } else if (e.key === 'Backspace' && !termDraft && terms.length > 0) {
                          removeTerm(terms[terms.length - 1]);
                        }
                      }}
                      // Commit on blur too: someone who types a word and then
                      // clicks the submit button expects that word to count.
                      onBlur={() => addTerm(termDraft)}
                      className="min-w-[8rem] flex-1 bg-transparent text-base text-fg outline-none placeholder:text-fg-subtle"
                    />
                  </div>
                </Field>

                <Field label="Search in">
                  <Segmented
                    ariaLabel="Search in"
                    options={[
                      { value: 'both', label: 'Title + summary' },
                      { value: 'title', label: 'Title' },
                      { value: 'summary', label: 'Summary' },
                    ]}
                    value={condition.matchIn}
                    onChange={(matchIn) =>
                      setCondition({
                        ...condition,
                        matchIn: matchIn as 'both' | 'title' | 'summary',
                      })
                    }
                  />
                </Field>
              </>
            )}

            {condition.kind === 'countdown' && (
              <Field label="Warn me this far ahead">
                <Select
                  ariaLabel="Lead time"
                  value={String(condition.leadMinutes)}
                  options={LEAD_CHOICES}
                  onChange={(value) => setCondition({ ...condition, leadMinutes: Number(value) })}
                />
              </Field>
            )}

            {/* Repeat and cooldown are collapsed because their defaults are
                right for almost every alarm, and two more decisions in front of
                the button is what made this form feel like configuration. The
                summary line keeps them visible without keeping them open. */}
            <div className="border-t border-line pt-4">
              <button
                type="button"
                onClick={() => setShowMore((open) => !open)}
                aria-expanded={showMore}
                className="text-base text-fg-muted transition-colors hover:text-fg"
              >
                {showMore ? 'Fewer options' : 'More options'}
                <span className="ml-2 text-xs text-fg-subtle">
                  {repeat === 'once' ? 'Notifies once' : `Repeats · ${cooldownLabel(cooldownMs)}`}
                </span>
              </button>

              {showMore && (
                <div className="mt-4 space-y-5">
                  <Field label="Repeat">
                    <Segmented
                      ariaLabel="Repeat"
                      options={[
                        { value: 'once', label: 'Once' },
                        { value: 'always', label: 'Every time' },
                      ]}
                      value={repeat}
                      onChange={(value) => setRepeat(value as 'once' | 'always')}
                    />
                  </Field>

                  {repeat === 'always' && (
                    <Field
                      label="Cooldown"
                      hint="The same alarm sends nothing again until this has elapsed."
                    >
                      <Select
                        ariaLabel="Cooldown"
                        value={String(cooldownMs)}
                        options={COOLDOWN_CHOICES}
                        onChange={(value) => setCooldownMs(Number(value))}
                      />
                    </Field>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* The answer column. */}
          <aside className="space-y-3 lg:sticky lg:top-0 lg:self-start">
            <div className="rounded-lg border border-line bg-surface-2 px-3.5 py-3">
              <p className="label">Reading now</p>
              <p className="mt-1 break-words font-mono tabnum text-lg text-fg">{readingText}</p>
              {condition.kind === 'threshold' && condition.value !== 0 && (
                <p className="mt-2 border-t border-line pt-2 font-mono text-base text-fg-muted">
                  {condition.op === 'above' ? '↑' : '↓'}{' '}
                  {formatFieldValue(activeField, condition.value)}
                </p>
              )}
            </div>

            <div className="rounded-lg border border-line px-3.5 py-3">
              <p className="label">This alarm</p>
              <p className="mt-1.5 text-base leading-relaxed text-fg-muted">
                {describeAlarm(previewAlarm)}
              </p>
            </div>

            {alreadyTrue && (
              <div className="rounded-lg border border-warn/30 bg-warn-bg px-3.5 py-3">
                <p className="flex items-center gap-1.5 text-base font-medium text-warn">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  Already true
                </p>
                <p className="mt-1 text-base leading-relaxed text-fg-muted">
                  The reading already meets this condition, so the alarm fires on the next check.
                  Move the level past the current reading if you meant to wait for a move.
                </p>
              </div>
            )}
          </aside>
        </div>
      </div>

      <div className="shrink-0 border-t border-line px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          {missingRequired.length > 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-warn">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              {missingRequired.map((spec) => spec.label).join(', ')} required.
            </p>
          ) : emptyKeywords ? (
            <p className="text-xs text-warn">Add at least one keyword.</p>
          ) : emptyStates ? (
            <p className="text-xs text-warn">Pick at least one status.</p>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={submit}
            disabled={!canSubmit}
            className={PRIMARY_BUTTON_CLASS}
          >
            Create alarm
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Round to the field's own precision.
 *
 * Without this an offset chip on a $67,412.38 reading produces
 * 70783.99900000001 — both wrong-looking in the input and a different number
 * from the one the preview sentence prints.
 */
function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function cooldownLabel(ms: number): string {
  return COOLDOWN_CHOICES.find((choice) => choice.value === String(ms))?.label ?? `${ms / MINUTE}m`;
}
