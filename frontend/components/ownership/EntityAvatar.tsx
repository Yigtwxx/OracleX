'use client';

import { useEffect, useRef, useState } from 'react';
import type { OwnershipEntity } from '@/lib/api';
import { countryFlag, monogram } from './format';

/** Holders read by the country they act for rather than by a corporate mark. */
const FLAG_FIRST_CATEGORIES: ReadonlySet<OwnershipEntity['category']> = new Set<
  OwnershipEntity['category']
>(['politician', 'central_bank']);

type AvatarSize = 'sm' | 'md' | 'lg';

const BOX: Record<AvatarSize, string> = {
  sm: 'h-7 w-7 text-[0.6rem]',
  md: 'h-10 w-10 text-xs',
  lg: 'h-12 w-12 text-sm',
};

/** The flag when it *is* the icon — sized to fill the box, not to sit in it. */
const FLAG_MAIN: Record<AvatarSize, string> = {
  sm: 'text-sm',
  md: 'text-xl',
  lg: 'text-2xl',
};

/** The flag when it only says where the holder is from. */
const FLAG_BADGE: Record<AvatarSize, string> = {
  sm: 'text-[0.5rem] -bottom-1 -right-1 px-[0.15rem]',
  md: 'text-[0.6rem] -bottom-1 -right-1 px-[0.15rem]',
  lg: 'text-[0.7rem] -bottom-1 -right-1 px-[0.2rem]',
};

/**
 * Below this, whatever came back is not the holder's mark.
 *
 * The favicon service answers a 128px request with a 16px generic globe when
 * the site has none — a 200, not an error, so `onError` never fires and the
 * card would sit there showing a stock icon as if it were Berkshire's. Anything
 * this small is also unrenderable in a 40px square regardless of where it came
 * from, so the same threshold covers both.
 */
const MIN_ICON_PX = 20;

interface EntityAvatarProps {
  entity: Pick<OwnershipEntity, 'name' | 'category' | 'country' | 'logo_url'>;
  size?: AvatarSize;
  className?: string;
}

/**
 * The mark beside a holder's name.
 *
 * Three things can stand in that square, and which one appears is a claim about
 * what identifies the holder. A company gets its own logo. A politician or a
 * central bank gets a flag, because the country is the identity — a logo would
 * be inventing a brand for a person in office. Anyone we have no mark for gets
 * a monogram, which says exactly that instead of borrowing someone else's.
 *
 * Where the logo leads, the flag stays on as a corner badge: the icon says who,
 * the badge says where, and neither answer is dropped for the other.
 *
 * A logo that fails to load — or that comes back too small to be one — falls
 * back to the monogram rather than leaving a torn-image box or a placeholder
 * globe. The failure is tracked per URL so switching holders re-tries with the
 * new one instead of inheriting the previous holder's outcome.
 */
export default function EntityAvatar({ entity, size = 'md', className = '' }: EntityAvatarProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const flag = countryFlag(entity.country);
  const flagIsIdentity = FLAG_FIRST_CATEGORIES.has(entity.category);
  const logo = entity.logo_url && entity.logo_url !== failedSrc ? entity.logo_url : null;
  const showLogo = Boolean(logo) && !flagIsIdentity;

  /**
   * Re-check an image that finished before React was listening.
   *
   * `onLoad` never fires retroactively, and a cached icon on server-rendered
   * markup is decoded before hydration attaches the handler — which is every
   * visit after the first. Without this pass the size check would work on a
   * cold load and quietly stop working on every warm one.
   */
  useEffect(() => {
    const img = imgRef.current;
    // Decoded dimensions, not completion: a placeholder served over a stalled
    // connection reports its size long before the transfer ends, and waiting
    // for `complete` there means waiting forever.
    if (!img || !logo) return;
    if (img.naturalWidth > 0 && img.naturalWidth < MIN_ICON_PX) setFailedSrc(logo);
  }, [logo]);

  return (
    <span
      className={`relative flex shrink-0 items-center justify-center overflow-visible rounded bg-surface-2 font-semibold text-fg-muted ${BOX[size]} ${className}`}
      aria-hidden
    >
      {showLogo ? (
        // object-contain, not cover: a wordmark cropped to a square stops being
        // the company's mark. The box is filled as far as the aspect allows.
        <img
          ref={imgRef}
          src={logo as string}
          alt=""
          loading="lazy"
          className="h-full w-full rounded object-contain"
          onError={() => setFailedSrc(logo)}
          onLoad={(event) => {
            if (event.currentTarget.naturalWidth < MIN_ICON_PX) setFailedSrc(logo);
          }}
        />
      ) : flagIsIdentity && flag ? (
        <span className={`leading-none ${FLAG_MAIN[size]}`}>{flag}</span>
      ) : (
        monogram(entity.name)
      )}

      {/* Only alongside a logo. On a monogram the square is already saying "no
          mark for them", and on a flag-first card the flag is the icon. */}
      {showLogo && flag && (
        <span
          className={`absolute rounded-full bg-surface leading-none ring-1 ring-line ${FLAG_BADGE[size]}`}
        >
          {flag}
        </span>
      )}
    </span>
  );
}
