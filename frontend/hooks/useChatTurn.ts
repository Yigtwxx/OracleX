'use client';

import { useSyncExternalStore } from 'react';
import {
  getServerSnapshot,
  getSnapshot,
  subscribe,
  type ChatTurnSnapshot,
} from '@/lib/chat-turn-store';

/**
 * The turn in flight, from the store that outlives this component's mount.
 *
 * `useSyncExternalStore` rather than React Query: the poll has to keep running
 * when nothing is subscribed and while the document is hidden, which is exactly
 * what a query cache is built not to do.
 */
export function useChatTurn(): ChatTurnSnapshot {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
