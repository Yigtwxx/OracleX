'use client';

import { useQuery } from '@tanstack/react-query';
import { loadReadings } from '@/lib/alarms/sources';
import { getAlarmSource } from '@/lib/alarms/registry';
import {
  DEFAULT_COOLDOWN_MS,
  type Alarm,
  type AlarmSourceId,
  type Reading,
} from '@/lib/alarms/types';

/**
 * The current reading for a source the user is configuring.
 *
 * Shown above the threshold input so nobody types a number blind. It shares the
 * engine's React Query cache, so opening the builder costs no extra request for
 * a source an alarm already watches.
 */
export function useSourceReading(
  sourceId: AlarmSourceId,
  params: Record<string, string>,
  enabled: boolean
) {
  const source = getAlarmSource(sourceId);
  const missingRequired = source.params.some((spec) => spec.required && !params[spec.key]?.trim());

  return useQuery<Reading | null>({
    queryKey: ['alarmReading', sourceId, params],
    enabled: enabled && !missingRequired,
    staleTime: source.minIntervalMs,
    // A symbol the backend cannot price answers 404, which is a real answer
    // about the input the user just typed — not a connection failure worth a
    // global toast.
    retry: false,
    meta: { silentError: true },
    queryFn: async () => {
      const probe: Alarm = {
        id: 'probe',
        sourceId,
        params,
        condition: source.defaultCondition,
        repeat: 'once',
        cooldownMs: DEFAULT_COOLDOWN_MS,
        enabled: true,
        createdAt: '',
        lastTriggeredAt: undefined,
        triggerCount: 0,
        seenKeys: [],
        armed: true,
      };
      const readings = await loadReadings(probe);
      return readings[0] ?? null;
    },
  });
}
