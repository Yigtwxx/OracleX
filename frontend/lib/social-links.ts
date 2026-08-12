/**
 * The platforms a profile may list, and the rules for each one.
 *
 * This mirrors `backend/services/social_links_service.py`, which is the
 * authority — the server re-validates everything and rebuilds every URL from
 * its own template. What lives here is the same knowledge in the shape the
 * editor needs: a placeholder to show, a pattern to grey out the save button
 * before a round trip, a brand colour for the icon.
 *
 * Deliberately free of JSX so vitest can reach it. `vitest.config.mts` collects
 * `lib/ ** / *.test.ts` under a node environment; the SVG glyphs live in
 * `components/profile/social-icons.tsx` instead.
 *
 * The handles are self-declared. Nothing here verifies ownership, and no
 * consumer of this module may present them as verified.
 */

export type SocialPlatformId =
  | 'x'
  | 'discord'
  | 'telegram'
  | 'github'
  | 'linkedin'
  | 'youtube'
  | 'instagram'
  | 'tiktok'
  | 'reddit'
  | 'twitch'
  | 'medium'
  | 'substack'
  | 'tradingview';

export interface SocialPlatform {
  id: SocialPlatformId;
  label: string;
  /** Absent where the platform has no addressable profile URL. */
  urlTemplate?: string;
  pattern: RegExp;
  brandColor: string;
  /** True where the platform's identifiers are case-insensitive. */
  lowercase: boolean;
  placeholder: string;
}

export const MAX_CUSTOM_LINKS = 3;
export const MAX_SOCIAL_LINKS = 16;
export const MAX_BIO_LENGTH = 200;
export const MAX_CUSTOM_LABEL_LENGTH = 40;
export const MAX_CUSTOM_URL_LENGTH = 200;

export const SOCIAL_PLATFORMS: readonly SocialPlatform[] = [
  {
    id: 'x',
    label: 'X',
    urlTemplate: 'https://x.com/{h}',
    pattern: /^[A-Za-z0-9_]{1,15}$/,
    brandColor: '#ffffff',
    lowercase: false,
    placeholder: 'yigtwx',
  },
  {
    // No URL: a modern Discord username is not addressable — discord.com/users
    // wants the numeric snowflake, which a user cannot read off their own
    // profile. The row renders as copyable text rather than a link that goes
    // nowhere.
    id: 'discord',
    label: 'Discord',
    pattern: /^[a-z0-9._]{2,32}$/,
    brandColor: '#5865f2',
    lowercase: true,
    placeholder: 'yigtwx',
  },
  {
    id: 'telegram',
    label: 'Telegram',
    urlTemplate: 'https://t.me/{h}',
    pattern: /^[A-Za-z0-9_]{5,32}$/,
    brandColor: '#26a5e4',
    lowercase: false,
    placeholder: 'yigtwx',
  },
  {
    id: 'github',
    label: 'GitHub',
    urlTemplate: 'https://github.com/{h}',
    pattern: /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/,
    brandColor: '#f0f6fc',
    lowercase: false,
    placeholder: 'Yigtwxx',
  },
  {
    id: 'linkedin',
    label: 'LinkedIn',
    urlTemplate: 'https://www.linkedin.com/in/{h}',
    pattern: /^[A-Za-z0-9-]{3,100}$/,
    brandColor: '#0a66c2',
    lowercase: false,
    placeholder: 'yigit-erdogan0',
  },
  {
    id: 'youtube',
    label: 'YouTube',
    urlTemplate: 'https://www.youtube.com/@{h}',
    pattern: /^[A-Za-z0-9._-]{3,30}$/,
    brandColor: '#ff0033',
    lowercase: false,
    placeholder: 'Yigtwx',
  },
  {
    id: 'instagram',
    label: 'Instagram',
    urlTemplate: 'https://instagram.com/{h}',
    pattern: /^[A-Za-z0-9._]{1,30}$/,
    brandColor: '#e4405f',
    lowercase: false,
    placeholder: 'yigtwx',
  },
  {
    id: 'tiktok',
    label: 'TikTok',
    urlTemplate: 'https://www.tiktok.com/@{h}',
    pattern: /^[A-Za-z0-9._]{2,24}$/,
    brandColor: '#25f4ee',
    lowercase: false,
    placeholder: 'yigtwx',
  },
  {
    id: 'reddit',
    label: 'Reddit',
    urlTemplate: 'https://reddit.com/user/{h}',
    pattern: /^[A-Za-z0-9_-]{3,20}$/,
    brandColor: '#ff4500',
    lowercase: false,
    placeholder: 'yigtwx7',
  },
  {
    id: 'twitch',
    label: 'Twitch',
    urlTemplate: 'https://twitch.tv/{h}',
    pattern: /^[A-Za-z0-9_]{4,25}$/,
    brandColor: '#9146ff',
    lowercase: true,
    placeholder: 'yigtwx',
  },
  {
    id: 'medium',
    label: 'Medium',
    urlTemplate: 'https://medium.com/@{h}',
    pattern: /^[A-Za-z0-9._-]{1,50}$/,
    brandColor: '#f5f5f5',
    lowercase: false,
    placeholder: 'yigtwx',
  },
  {
    id: 'substack',
    label: 'Substack',
    urlTemplate: 'https://{h}.substack.com',
    pattern: /^[a-z0-9-]{1,63}$/,
    brandColor: '#ff6719',
    lowercase: true,
    placeholder: 'my-letter',
  },
  {
    id: 'tradingview',
    label: 'TradingView',
    urlTemplate: 'https://www.tradingview.com/u/{h}/',
    pattern: /^[A-Za-z0-9_]{1,30}$/,
    brandColor: '#2962ff',
    lowercase: false,
    placeholder: 'yigtwx',
  },
];

export const PLATFORM_BY_ID: Record<string, SocialPlatform | undefined> = Object.fromEntries(
  SOCIAL_PLATFORMS.map((platform) => [platform.id, platform])
);

/** Trim, drop a pasted leading `@`, and lowercase where the platform is case-blind. */
export function normaliseHandle(platform: string, raw: string): string {
  let handle = raw.trim();
  if (handle.startsWith('@')) handle = handle.slice(1);
  return PLATFORM_BY_ID[platform]?.lowercase ? handle.toLowerCase() : handle;
}

/** The profile URL for `handle`, or undefined where the platform has none. */
export function buildProfileUrl(platform: string, handle: string): string | undefined {
  const template = PLATFORM_BY_ID[platform]?.urlTemplate;
  return template ? template.replace('{h}', handle) : undefined;
}

export function isValidHandle(platform: string, handle: string): boolean {
  const spec = PLATFORM_BY_ID[platform];
  return spec ? spec.pattern.test(handle) : false;
}

/**
 * Whether a free-form link is safe to put in an `href`.
 *
 * The scheme allowlist is the whole point: `javascript:` and `data:` are what
 * turn a profile field into stored XSS. The server checks this again — this
 * copy exists so the editor can say no before a round trip.
 */
export function isSafeCustomUrl(url: string): boolean {
  const trimmed = url.trim();
  if (!trimmed || trimmed.length > MAX_CUSTOM_URL_LENGTH) return false;

  try {
    const parsed = new URL(trimmed);
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.host.length > 0;
  } catch {
    return false;
  }
}
