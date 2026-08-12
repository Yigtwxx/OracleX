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
      },
      transitionDuration: {
        DEFAULT: '120ms',
      },
    },
  },
  plugins: [],
};

export default config;
