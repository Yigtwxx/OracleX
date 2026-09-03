'use client';

import { useEffect, useRef } from 'react';
import { useStore } from '@/store/useStore';
import { loadReadings } from '@/lib/alarms/sources';
import { evaluateAlarm } from '@/lib/alarms/evaluate';
import {
  describeAlarmShort,
  describeMailHeadline,
  describeMailLead,
  describeSubject,
  distanceFromThreshold,
  thresholdDisplay,
} from '@/lib/alarms/describe';
import { getAlarmSource } from '@/lib/alarms/registry';
import { playAlarmSound, showOsNotification } from '@/lib/alarms/notify';
import {
  formatFiredAt,
  isAlarmEmailRejected,
  sendAlarmEmail,
  toneForAlarm,
} from '@/lib/alarms/email';
import { showAlarmToast } from '@/lib/queryClient';
import type { Alarm, Reading, TriggerEvent } from '@/lib/alarms/types';

/** How often the engine looks. Per-source rate limiting is React Query's job. */
const TICK_MS = 15_000;

/**
 * The global alarm watcher, mounted once in ClientShell.
 *
 * Two things it deliberately does not do:
 *
 * It does not schedule per source. `sources.ts` reads through
 * `queryClient.fetchQuery` with `staleTime` set from each source's
 * `minIntervalMs`, so a ten-minute source polled every fifteen seconds costs one
 * cache read and no request. Two alarms on one source share that request too.
 *
 * It does not decide anything. `evaluateAlarm` is pure and tested; this hook
 * applies whatever it returns.
 *
 * The interval is installed once. The previous implementation depended on the
 * alarm array, so adding, deleting or firing an alarm tore the timer down and
 * restarted it — which also fired an immediate extra check every time.
 */
export function useAlarmEngine() {
  const alarmsRef = useRef<Alarm[]>([]);
  // Reading the store through a ref rather than through the effect's deps is
  // what keeps the interval stable across every alarm mutation.
  alarmsRef.current = useStore((state) => state.alarms);

  const running = useRef(false);

  useEffect(() => {
    async function tick() {
      // The previous pass can outlive a tick on a slow network; overlapping runs
      // would double-notify, because both would see the same un-patched alarm.
      if (running.current) return;
      const active = alarmsRef.current.filter((alarm) => alarm.enabled);
      if (active.length === 0) return;

      running.current = true;
      try {
        for (const alarm of active) {
          // Re-read: an earlier alarm in this pass may have written the store,
          // and a stale copy would re-evaluate against a spent trigger count.
          const current = useStore.getState().alarms.find((a) => a.id === alarm.id);
          if (!current || !current.enabled) continue;

          let readings;
          try {
            readings = await loadReadings(current);
          } catch (error) {
            // One unreachable source must not stop the others. The user already
            // sees the failure through React Query's own error toast.
            console.warn(`[alarms] ${current.sourceId} could not be read`, error);
            continue;
          }

          for (const reading of readings) {
            const latest = useStore.getState().alarms.find((a) => a.id === current.id);
            if (!latest) break;

            const decision = evaluateAlarm(latest, reading, Date.now());
            if (decision.action === 'none') continue;

            if (decision.action === 'rearm') {
              useStore.getState().updateAlarm(latest.id, decision.patch);
              continue;
            }

            const event = buildEvent(latest, decision.detail);
            playAlarmSound();
            showOsNotification(event.title, event.body, latest.id);
            showAlarmToast(`${event.title} — ${event.body}`);
            useStore.getState().recordAlarmTrigger(latest.id, decision.patch, event);
            // Not awaited. A slow relay must not hold up the rest of this pass,
            // and the alarm has already been recorded and shown three other
            // ways — the mail is the one channel whose failure changes nothing
            // the user can see right now.
            void mailTrigger(latest, event, decision.detail, reading);
          }
        }
      } finally {
        running.current = false;
      }
    }

    void tick();
    const id = window.setInterval(() => void tick(), TICK_MS);
    return () => window.clearInterval(id);
  }, []);
}

/**
 * Mail one fired alarm, if this browser has a confirmed address.
 *
 * Reads the address at send time rather than through a hook: the interval is
 * installed once and never re-created, so a closure over it would keep mailing
 * an address the user removed ten minutes ago.
 */
async function mailTrigger(
  alarm: Alarm,
  event: TriggerEvent,
  detail: string,
  reading: Reading
): Promise<void> {
  const identity = useStore.getState().alarmEmail;
  if (!identity) return;

  // The raw number, not the formatted string, so the distance is arithmetic
  // rather than a parse of "$72,450.00". Absent for every non-threshold
  // condition, and `distanceFromThreshold` returns undefined rather than
  // inventing a figure.
  const rawValue =
    alarm.condition.kind === 'threshold' ? reading.values[alarm.condition.field] : null;
  const distance = distanceFromThreshold(alarm, rawValue);

  try {
    await sendAlarmEmail(identity, {
      eventId: event.id,
      sourceLabel: getAlarmSource(alarm.sourceId).label,
      subjectLine: describeSubject(alarm),
      observed: detail,
      rule: describeAlarmShort(alarm),
      firedAtLabel: formatFiredAt(event.firedAt),
      tone: toneForAlarm(alarm),
      triggerCount: alarm.triggerCount + 1,
      headline: describeMailHeadline(alarm),
      lead: describeMailLead(alarm, detail, distance),
      threshold: thresholdDisplay(alarm),
      distance,
    });
  } catch (error) {
    if (isAlarmEmailRejected(error)) {
      // The backend no longer honours this token — the signing secret was
      // rotated, or the deployment changed. Dropping it sends the user back to
      // the confirmation form instead of failing silently on every alarm from
      // here on.
      useStore.getState().setAlarmEmail(undefined);
      showAlarmToast('Email alerts need confirming again — open the Alarm Center.');
      return;
    }
    console.warn('[alarms] trigger mail could not be sent', error);
  }
}

function buildEvent(alarm: Alarm, detail: string): TriggerEvent {
  return {
    id: `${alarm.id}_${Date.now()}`,
    alarmId: alarm.id,
    sourceId: alarm.sourceId,
    title: `🔔 ${describeSubject(alarm)}`,
    // The observed value first, then the rule it broke — reading the value is
    // the point, and the rule is context for it.
    body: `${detail} · ${describeAlarmShort(alarm)}`,
    firedAt: new Date().toISOString(),
  };
}
