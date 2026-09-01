import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    // Not only components: `lib/heatmap-scale.ts` holds the heatmap's colour
    // buckets, and a class Tailwind never scans is silently never generated —
    // the tiles rendered fully transparent with no error anywhere.
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
    './hooks/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Surfaces
        bg: 'var(--bg)',
        surface: {
          DEFAULT: 'var(--surface)',
          2: 'var(--surface-2)',
        },
        line: {
          DEFAULT: 'var(--border)',
          strong: 'var(--border-strong)',
        },

        // Text
        fg: {
          DEFAULT: 'var(--fg)',
          muted: 'var(--fg-muted)',
          subtle: 'var(--fg-subtle)',
        },

        // Semantic — the only colours allowed to appear in the UI
        up: {
          DEFAULT: 'var(--up)',
          bg: 'var(--up-bg)',
        },
        down: {
          DEFAULT: 'var(--down)',
          bg: 'var(--down-bg)',
        },
        warn: {
          DEFAULT: 'var(--warn)',
          bg: 'var(--warn-bg)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          bg: 'var(--accent-bg)',
          // Label colour for a solid accent fill. Always paired with
          // `bg-accent`, never used on its own — the landing page flips the
          // accent to white and this flips with it.
          fg: 'var(--accent-fg)',
        },

        // Chat response mode — identifies which Oracle is answering
        mode: {
          concise: 'var(--mode-concise)',
          'concise-bg': 'var(--mode-concise-bg)',
          'concise-solid': 'var(--mode-concise-solid)',
          detailed: 'var(--mode-detailed)',
          'detailed-bg': 'var(--mode-detailed-bg)',
          'detailed-solid': 'var(--mode-detailed-solid)',
        },

        // Asset identity — labels an entity, never decorates
        data: {
          btc: 'var(--data-btc)',
          eth: 'var(--data-eth)',
          gold: 'var(--data-gold)',
          silver: 'var(--data-silver)',
          platinum: 'var(--data-platinum)',
          palladium: 'var(--data-palladium)',
          copper: 'var(--data-copper)',
        },

        // Heatmap ramps — colour encodes magnitude, not decoration
        heat: {
          'up-1': 'var(--heat-up-1)',
          'up-2': 'var(--heat-up-2)',
          'up-3': 'var(--heat-up-3)',
          'up-4': 'var(--heat-up-4)',
          'down-1': 'var(--heat-down-1)',
          'down-2': 'var(--heat-down-2)',
          'down-3': 'var(--heat-down-3)',
          'down-4': 'var(--heat-down-4)',
          'seq-1': 'var(--heat-seq-1)',
          'seq-2': 'var(--heat-seq-2)',
          'seq-3': 'var(--heat-seq-3)',
          'seq-4': 'var(--heat-seq-4)',
        },

        // Chart series
        chart: {
          1: 'var(--chart-1)',
          2: 'var(--chart-2)',
          3: 'var(--chart-3)',
          4: 'var(--chart-4)',
          5: 'var(--chart-5)',
          6: 'var(--chart-6)',
          7: 'var(--chart-7)',
        },
      },
      borderColor: {
        DEFAULT: 'var(--border)',
      },
      borderRadius: {
        md: '6px',
        lg: '8px',
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px' }],
        xs: ['11px', { lineHeight: '16px' }],
        sm: ['12px', { lineHeight: '18px' }],
        base: ['13px', { lineHeight: '20px' }],
        md: ['14px', { lineHeight: '21px' }],
        lg: ['16px', { lineHeight: '24px' }],
        xl: ['20px', { lineHeight: '28px' }],
        '2xl': ['24px', { lineHeight: '32px' }],

        // Marketing only — the terminal scale above deliberately stops at 24px,
        // and these are namespaced rather than continued as 3xl/4xl so that a
        // `text-display-1` inside the app reads as a mistake at a glance.
        // Fluid because a fixed headline overflows a 360px phone and the app has
        // no responsive type scale to fall back on.
        //
        // Kept close to the terminal scale on purpose. The page is a chart with
        // notes written on it, and a 72px headline over a 11px mono annotation
        // is two products stapled together — the copy has to sound like it came
        // off the same desk as the tape it sits on.
        'display-1': [
          'clamp(32px, 5.4vw, 52px)',
          { lineHeight: '1.06', letterSpacing: '-0.025em' },
        ],
        'display-2': [
          'clamp(24px, 3.2vw, 30px)',
          { lineHeight: '1.15', letterSpacing: '-0.015em' },
        ],
        lead: ['16px', { lineHeight: '26px' }],
      },
      transitionDuration: {
        DEFAULT: '120ms',
      },
    },
  },
  plugins: [],
};

export default config;
