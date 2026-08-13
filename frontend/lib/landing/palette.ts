export interface RenderPalette {
  readonly up: string;
  readonly down: string;
  readonly accent: string;
  readonly fg: string;
  readonly fgMuted: string;
  readonly fgSubtle: string;
  readonly line: string;
  readonly surface: string;
  readonly mono: string;
}

const FALLBACKS: RenderPalette = {
  up: '#22c55e',
  down: '#ef4444',
  accent: '#2f6feb',
  fg: '#e8e8ea',
  fgMuted: '#9a9aa3',
  fgSubtle: '#6b6b74',
  line: '#26262c',
  surface: '#111114',
  mono: 'ui-monospace, monospace',
};

/**
 * Pulls the canvas colours off the cascade at runtime rather than restating them.
 *
 * Same technique as ChatModeBackdrop's `readToken` — the scene physically cannot
 * drift away from globals.css, because it never holds a colour of its own.
 *
 * `from` matters: the landing page overrides `--accent` on `.landing`, and
 * reading off `:root` would pick up the terminal's brighter one and put the
 * canvas out of step with the copy sitting on it. Pass an element inside the
 * scope whose colours you want.
 */
export function readPalette(from?: Element | null): RenderPalette {
  if (typeof window === 'undefined') return FALLBACKS;
  const styles = getComputedStyle(from ?? document.documentElement);
  const read = (name: string, fallback: string): string => {
    const value = styles.getPropertyValue(name).trim();
    return value || fallback;
  };

  return {
    up: read('--up', FALLBACKS.up),
    down: read('--down', FALLBACKS.down),
    accent: read('--accent', FALLBACKS.accent),
    fg: read('--fg', FALLBACKS.fg),
    fgMuted: read('--fg-muted', FALLBACKS.fgMuted),
    fgSubtle: read('--fg-subtle', FALLBACKS.fgSubtle),
    line: read('--line', FALLBACKS.line),
    surface: read('--surface', FALLBACKS.surface),
    mono: read('--font-mono', FALLBACKS.mono),
  };
}

/**
 * `#rrggbb` → `rgba(...)`. The tokens are all hex, but a non-hex value (a named
 * colour, an `oklch()`) falls through unchanged rather than rendering as black.
 */
export function withAlpha(color: string, alpha: number): string {
  const hex = color.replace(/^#/, '');
  if (!/^[0-9a-f]{3}$|^[0-9a-f]{6}$/i.test(hex)) return color;
  const full =
    hex.length === 3
      ? hex
          .split('')
          .map((c) => c + c)
          .join('')
      : hex;
  const int = Number.parseInt(full, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, alpha))})`;
}
