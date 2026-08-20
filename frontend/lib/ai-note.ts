/**
 * The shared envelope every model-written note arrives in.
 *
 * Three surfaces render one of these — the macro regime read, the chain anomaly
 * strip and the institutional flow panel — and all three follow the same rule:
 * the note is commentary on figures that were computed in Python and are always
 * present. So a missing note is never an error state. It is a paragraph that did
 * not arrive, on a page that is already complete without it.
 *
 * The logic lives here rather than in the components because this repo tests
 * `lib/*.ts` and does not test components. Anything with a branch in it belongs
 * on this side of the line.
 *
 * Named `aiNote` throughout, never `note`: `Note`, `fetchNotes` and
 * `queryKeys.notes` already mean the notes a *user* writes on a report, and one
 * collision there would be a genuinely confusing bug to read.
 */

/**
 * `ready` carries prose. `generating` means a run is in flight and the client
 * should look again shortly. `unavailable` is terminal for this page load —
 * the model layer is off, the provider chain is down, or there was nothing
 * worth saying — and must stop the polling rather than retry into it.
 */
export type AiNoteStatus = 'ready' | 'generating' | 'unavailable';

export interface AiNote {
  status: AiNoteStatus;
  note: string | null;
  generated_at: string | null;
  /** Why there is no note. `nothing_flagged` is a quiet board, not a failure. */
  reason: string | null;
}

/**
 * How often to look again while a note is being written.
 *
 * Deliberately slower than the 1.5s report-job poll: a local model takes tens of
 * seconds to write two sentences, so a faster interval would only add requests
 * that are certain to miss.
 */
export const NOTE_POLL_INTERVAL_MS = 4000;

/** Whether a run is still in flight. Anything else is settled. */
export function isGenerating(aiNote: AiNote | null | undefined): boolean {
  return aiNote?.status === 'generating';
}

/**
 * The prose to render, or null.
 *
 * Guards the case a `status` check alone would miss: `ready` with an empty
 * string. Rendering that would leave a paragraph of blank space where the note
 * should be, which reads as a layout bug rather than as an absent note.
 */
export function aiNoteText(aiNote: AiNote | null | undefined): string | null {
  if (aiNote?.status !== 'ready') return null;
  const text = aiNote.note?.trim();
  return text ? text : null;
}

/**
 * The React Query `refetchInterval` for a payload carrying a note.
 *
 * Returns `false` — stop polling — for every settled state, including the ones
 * that will never settle any further. A client that kept polling an
 * `unavailable` note would re-ask a provider chain already known to be down,
 * every few seconds, for as long as the tab stayed open.
 */
export function aiNotePollInterval(aiNote: AiNote | null | undefined): number | false {
  return isGenerating(aiNote) ? NOTE_POLL_INTERVAL_MS : false;
}
