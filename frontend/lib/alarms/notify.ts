'use client';

/**
 * The two channels an alarm reaches the user through when the page is not in
 * front of them: a sound and an OS notification. The in-app toast is raised
 * separately by the engine, because it is only useful when they are looking.
 *
 * Kept out of `evaluate.ts` so the decision logic stays testable in node.
 */

const BEEP_GAP_SECONDS = 0.2;
const BEEP_LENGTH_SECONDS = 0.5;

/**
 * Two rising beeps.
 *
 * Both oscillators are scheduled against a single `t0` captured up front. The
 * previous implementation started the second one inside a `setTimeout` and then
 * read `currentTime` again, so its gain ramp was scheduled 200ms in the past
 * and the note played at full volume with no decay.
 */
export function playAlarmSound(): void {
  try {
    const AudioCtor =
      window.AudioContext ??
      (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtor) return;

    const context = new AudioCtor();
    const t0 = context.currentTime;

    const frequencies = [880, 1100];
    for (let index = 0; index < frequencies.length; index += 1) {
      const frequency = frequencies[index];
      const start = t0 + index * BEEP_GAP_SECONDS;
      const oscillator = context.createOscillator();
      const gain = context.createGain();

      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.frequency.value = frequency;
      oscillator.type = 'sine';

      gain.gain.setValueAtTime(0.3, start);
      gain.gain.exponentialRampToValueAtTime(0.01, start + BEEP_LENGTH_SECONDS);
      oscillator.start(start);
      oscillator.stop(start + BEEP_LENGTH_SECONDS);
    }

    // Release the hardware once the tail has played; a context per alarm would
    // otherwise accumulate until the browser refuses to open another.
    window.setTimeout(
      () => void context.close().catch(() => undefined),
      (BEEP_GAP_SECONDS + BEEP_LENGTH_SECONDS) * 1000 + 100
    );
  } catch {
    // Audio is a courtesy; the toast and the OS notification still land.
  }
}

/** Ask once, on the first alarm the user creates. Never on page load. */
export function requestNotificationPermission(): void {
  if (typeof window === 'undefined' || !('Notification' in window)) return;
  if (Notification.permission === 'default') void Notification.requestPermission();
}

export function notificationsAllowed(): boolean {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    Notification.permission === 'granted'
  );
}

export function showOsNotification(title: string, body: string, tag: string): void {
  if (!notificationsAllowed()) return;
  try {
    new Notification(title, { body, icon: '/favicon.ico', tag, requireInteraction: true });
  } catch {
    // Some browsers refuse a constructed Notification outside a service worker.
  }
}
