/**
 * The "a key would show you more here" prompt, as data.
 *
 * Every board that leans on an optional upstream already knows it is degraded —
 * `cpi_source === null`, `deflation.reason === 'cpi_key_missing'`,
 * `source === 'venues'`. This module turns those per-endpoint signals into one
 * notice model so the strip reads the same everywhere and no page has to invent
 * its own copy.
 *
 * Deliberately not an API call: the pages already receive the signal in the
 * payload they render, and a second request per board to ask "is a key set"
 * would be a round trip to learn what is already on screen.
 */

/** The upstreams a reader can supply a key for, plus the one they cannot. */
export type ProviderKey = 'evds' | 'coinalyze' | 'sec';

export interface ProviderNotice {
  provider: ProviderKey;
  /** Headline — what is missing, in the reader's terms rather than the env var's. */
  title: string;
  /** One sentence on what a key would add. Never implies the page is broken. */
  body: string;
  /** Where the settings live. Empty for server-scoped upstreams. */
  href: string;
  /** Label for the action, or empty when there is nothing the reader can do. */
  action: string;
}

const PROFILE_HREF = '/profile?tab=data';

/**
 * Turkish copy throughout: these strips appear on the BIST boards, which are
 * Turkish-language surfaces. The derivatives one is Turkish too for consistency
 * with the rest of the terminal's notices.
 */
const NOTICES: Record<ProviderKey, ProviderNotice> = {
  evds: {
    provider: 'evds',
    title: 'Enflasyon serisi tanımlı değil',
    body: 'TCMB EVDS anahtarı eklersen getiriler nominal yerine reel olarak da hesaplanır. Anahtar ücretsiz.',
    href: PROFILE_HREF,
    action: 'Anahtar ekle',
  },
  coinalyze: {
    provider: 'coinalyze',
    title: 'Açık pozisyon geçmişi 30 günle sınırlı',
    body: 'Coinalyze anahtarı eklersen borsaların 30 günlük istatistik ucu yerine tam günlük geçmiş gelir. Anahtar ücretsiz.',
    href: PROFILE_HREF,
    action: 'Anahtar ekle',
  },
  // No href: the ownership board is rebuilt by a scheduler from a server-wide
  // contact address, so there is nothing a reader can set. Saying so is still
  // better than a stale board with no explanation.
  sec: {
    provider: 'sec',
    title: 'SEC verisi yenilenmiyor',
    body: 'Sunucuda SEC_USER_AGENT tanımlı değil; tablo en son alınan kayıtları gösteriyor.',
    href: '',
    action: '',
  },
};

/**
 * The notice for `provider`, or undefined when nothing should be shown.
 *
 * `missing` is the page's own degraded-state signal. Passing false returns
 * undefined so a caller can write `providerNotice('evds', !data.cpi_source)`
 * without a branch.
 */
export function providerNotice(
  provider: ProviderKey,
  missing: boolean
): ProviderNotice | undefined {
  return missing ? NOTICES[provider] : undefined;
}

/** Whether a notice offers the reader something to do about it. */
export function isActionable(notice: ProviderNotice): boolean {
  return notice.href !== '' && notice.action !== '';
}
