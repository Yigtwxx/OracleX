/**
 * Region metadata for the index panel.
 *
 * Literal maps rather than anything constructed at runtime: a flag built from a
 * region code by arithmetic on Unicode regional-indicator points renders as two
 * stray letters the moment an unexpected code arrives, and "EU" has no flag by
 * that construction at all.
 */

export interface RegionMeta {
  flag: string;
  /** The section a region is filed under, in reading order. */
  bloc: 'americas' | 'europe' | 'asiaPacific';
}

export const REGION_META: Record<string, RegionMeta> = {
  US: { flag: '🇺🇸', bloc: 'americas' },
  UK: { flag: '🇬🇧', bloc: 'europe' },
  DE: { flag: '🇩🇪', bloc: 'europe' },
  FR: { flag: '🇫🇷', bloc: 'europe' },
  EU: { flag: '🇪🇺', bloc: 'europe' },
  TR: { flag: '🇹🇷', bloc: 'europe' },
  JP: { flag: '🇯🇵', bloc: 'asiaPacific' },
  HK: { flag: '🇭🇰', bloc: 'asiaPacific' },
  AU: { flag: '🇦🇺', bloc: 'asiaPacific' },
};

/** Blocs in the order the panel lists them, following the trading day west. */
export const BLOC_ORDER: RegionMeta['bloc'][] = ['americas', 'europe', 'asiaPacific'];

export const BLOC_LABEL: Record<RegionMeta['bloc'], string> = {
  americas: 'Americas',
  europe: 'Europe',
  asiaPacific: 'Asia-Pacific',
};

/** Fallback for a region the map does not know, so an unlisted index still lists. */
export const UNKNOWN_REGION: RegionMeta = { flag: '🏳️', bloc: 'asiaPacific' };

export function regionMeta(region: string): RegionMeta {
  return REGION_META[region] ?? UNKNOWN_REGION;
}
