import { describe, expect, it } from 'vitest';

import {
  MAX_BIO_LENGTH,
  MAX_CUSTOM_LINKS,
  PLATFORM_BY_ID,
  SOCIAL_PLATFORMS,
  buildProfileUrl,
  isSafeCustomUrl,
  isValidHandle,
  normaliseHandle,
} from '@/lib/social-links';

describe('the registry', () => {
  it('carries the thirteen platforms the design settled on', () => {
    expect(SOCIAL_PLATFORMS.map((p) => p.id)).toEqual([
      'x',
      'discord',
      'telegram',
      'github',
      'linkedin',
      'youtube',
      'instagram',
      'tiktok',
      'reddit',
      'twitch',
      'medium',
      'substack',
      'tradingview',
    ]);
  });

  it('agrees with the backend on the caps', () => {
    expect(MAX_CUSTOM_LINKS).toBe(3);
    expect(MAX_BIO_LENGTH).toBe(200);
  });

  it('gives every platform a brand colour and a placeholder', () => {
    for (const platform of SOCIAL_PLATFORMS) {
      expect(platform.brandColor).toMatch(/^#[0-9a-f]{6}$/i);
      expect(platform.placeholder.length).toBeGreaterThan(0);
    }
  });
});

describe('normaliseHandle', () => {
  it('strips a pasted leading @', () => {
    expect(normaliseHandle('x', '@yigtwx')).toBe('yigtwx');
  });

  it('trims surrounding space', () => {
    expect(normaliseHandle('x', '  yigtwx  ')).toBe('yigtwx');
  });

  it('lowercases only where the platform is case-blind', () => {
    expect(normaliseHandle('substack', 'My-Letter')).toBe('my-letter');
    expect(normaliseHandle('github', 'Yigtwxx')).toBe('Yigtwxx');
  });
});

describe('buildProfileUrl', () => {
  it.each([
    ['x', 'yigtwx', 'https://x.com/yigtwx'],
    ['telegram', 'yigtwx', 'https://t.me/yigtwx'],
    ['github', 'Yigtwxx', 'https://github.com/Yigtwxx'],
    ['youtube', 'Yigtwx', 'https://www.youtube.com/@Yigtwx'],
    ['substack', 'my-letter', 'https://my-letter.substack.com'],
    ['tradingview', 'yigtwx', 'https://www.tradingview.com/u/yigtwx/'],
  ])('builds the %s url', (platform, handle, expected) => {
    expect(buildProfileUrl(platform, handle)).toBe(expected);
  });

  it('has no url for discord, whose usernames are not addressable', () => {
    expect(buildProfileUrl('discord', 'yigtwx')).toBeUndefined();
    expect(PLATFORM_BY_ID.discord?.urlTemplate).toBeUndefined();
  });

  it('has no url for an unknown platform', () => {
    expect(buildProfileUrl('myspace', 'someone')).toBeUndefined();
  });
});

describe('isValidHandle', () => {
  it.each([
    ['x', 'yigtwx'],
    ['github', 'Yigtwxx'],
    ['telegram', 'yigtwx'],
    ['reddit', 'yigtwx7'],
    ['tradingview', 'yigtwx'],
  ])('accepts a real %s handle', (platform, handle) => {
    expect(isValidHandle(platform, handle)).toBe(true);
  });

  it.each([
    ['x', 'a'.repeat(16)],
    ['x', 'has spaces'],
    ['github', '-leading-hyphen'],
    ['telegram', 'abc'],
    ['substack', 'Not_Lowercase'],
    ['myspace', 'someone'],
  ])('refuses %s / %s', (platform, handle) => {
    expect(isValidHandle(platform, handle)).toBe(false);
  });
});

describe('isSafeCustomUrl', () => {
  it.each(['https://example.com', 'http://example.com/path?q=1'])('accepts %s', (url) => {
    expect(isSafeCustomUrl(url)).toBe(true);
  });

  // These are what turn a profile field into stored XSS.
  it.each([
    'javascript:alert(1)',
    'data:text/html;base64,PHNjcmlwdD4=',
    'file:///etc/passwd',
    'ftp://example.com',
    'example.com',
    '',
  ])('refuses %s', (url) => {
    expect(isSafeCustomUrl(url)).toBe(false);
  });
});

describe('the two registries agree', () => {
  // The backend re-validates everything, so a divergence here does not create a
  // hole — it creates a form that accepts a handle the server then rejects.
  it('uses the same url templates the backend does', () => {
    const backendTemplates: Record<string, string | undefined> = {
      x: 'https://x.com/{h}',
      discord: undefined,
      telegram: 'https://t.me/{h}',
      github: 'https://github.com/{h}',
      linkedin: 'https://www.linkedin.com/in/{h}',
      youtube: 'https://www.youtube.com/@{h}',
      instagram: 'https://instagram.com/{h}',
      tiktok: 'https://www.tiktok.com/@{h}',
      reddit: 'https://reddit.com/user/{h}',
      twitch: 'https://twitch.tv/{h}',
      medium: 'https://medium.com/@{h}',
      substack: 'https://{h}.substack.com',
      tradingview: 'https://www.tradingview.com/u/{h}/',
    };

    for (const platform of SOCIAL_PLATFORMS) {
      expect(platform.urlTemplate).toBe(backendTemplates[platform.id]);
    }
  });
});
