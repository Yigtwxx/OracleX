// GENERATED FILE — do not edit by hand.
// Regenerate with: python scripts/build_repo_facts.py
//
// Every number the marketing pages state about this repository comes from here,
// measured from the sources rather than counted by eye. `--check` runs in CI, so
// a figure that stops being true fails the build instead of quietly ageing.

export interface MethodCount {
  readonly method: string;
  readonly count: number;
}

export interface McpGroup {
  readonly label: string;
  readonly tools: readonly string[];
}

export interface HealthRow {
  readonly key: string;
  readonly label: string;
  readonly critical: boolean;
  readonly upstreams: number;
}

export interface TestSuite {
  readonly name: string;
  readonly tests: number;
  readonly files: number;
}

export const VERSION = '1.4.0';

export const API = {
  paths: 178,
  operations: 203,
  authRequired: 95,
  routers: 26,
  websockets: [
    '/ws/prices',
  ],
  methods: [
    {
      method: 'GET',
      count: 140,
    },
    {
      method: 'POST',
      count: 39,
    },
    {
      method: 'DELETE',
      count: 16,
    },
    {
      method: 'PUT',
      count: 6,
    },
    {
      method: 'PATCH',
      count: 2,
    },
  ],
} as const;

export const MCP = {
  total: 36,
  groups: [
    {
      label: 'Instance',
      tools: [
        'check_instance',
      ],
    },
    {
      label: 'Prices and levels',
      tools: [
        'get_price',
        'get_technical_levels',
        'get_candles',
        'get_asset_fundamentals',
        'get_market_overview',
        'get_market_indices',
      ],
    },
    {
      label: 'News',
      tools: [
        'list_news',
        'get_news_analysis',
        'find_similar_news',
      ],
    },
    {
      label: 'Reports, macro, chains',
      tools: [
        'get_analysis_report',
        'get_macro_regime',
        'get_macro_board',
        'get_chains_board',
        'get_chain_anomalies',
      ],
    },
    {
      label: 'Derivatives, flow, ownership',
      tools: [
        'get_liquidation_map',
        'get_funding_rates',
        'get_whale_flow',
        'get_ownership',
        'get_ownership_moves',
      ],
    },
    {
      label: 'Memory',
      tools: [
        'search_memory',
        'get_symbol_history',
        'compare_assets',
        'get_daily_brief',
      ],
    },
    {
      label: 'The Oracle itself',
      tools: [
        'ask_oracle',
        'get_watchlist',
      ],
    },
    {
      label: 'Borsa İstanbul',
      tools: [
        'get_bist_overview',
        'get_bist_stock',
        'get_bist_fund',
        'get_bist_disclosures',
        'get_turkish_macro',
        'get_viop_positioning',
      ],
    },
    {
      label: 'Prediction markets',
      tools: [
        'get_prediction_markets',
        'get_prediction_market',
        'analyse_prediction_market',
        'get_prediction_analysis_job',
      ],
    },
  ],
} as const;

export const SKILLS = [
  {
    name: 'oracle-x-api',
    version: '1.4.0',
    references: 3,
    examples: 4,
    generated: {
      file: 'references/endpoints.md',
      lines: 999,
      endpoints: 65,
      groups: 13,
    },
  },
  {
    name: 'oracle-x-bist',
    version: '1.4.0',
    references: 2,
    examples: 0,
    generated: {
      file: 'references/endpoints.md',
      lines: 619,
      endpoints: 36,
      groups: 1,
    },
  },
  {
    name: 'oracle-x-dev',
    version: '1.4.0',
    references: 5,
    examples: 0,
    generated: null,
  },
] as const;

export const HEALTH = {
  categories: 11,
  critical: 3,
  upstreams: 45,
  rows: [
    {
      key: 'prices_crypto',
      label: 'Crypto Prices',
      critical: true,
      upstreams: 5,
    },
    {
      key: 'stream',
      label: 'Live Stream',
      critical: true,
      upstreams: 1,
    },
    {
      key: 'database',
      label: 'Database',
      critical: true,
      upstreams: 1,
    },
    {
      key: 'stocks',
      label: 'Stocks',
      critical: false,
      upstreams: 3,
    },
    {
      key: 'news',
      label: 'News',
      critical: false,
      upstreams: 4,
    },
    {
      key: 'onchain',
      label: 'On-chain',
      critical: false,
      upstreams: 11,
    },
    {
      key: 'macro',
      label: 'Macro & Sentiment',
      critical: false,
      upstreams: 8,
    },
    {
      key: 'ai',
      label: 'AI / LLM',
      critical: false,
      upstreams: 1,
    },
    {
      key: 'prediction',
      label: 'Prediction Markets',
      critical: false,
      upstreams: 3,
    },
    {
      key: 'notifications',
      label: 'Notifications',
      critical: false,
      upstreams: 1,
    },
    {
      key: 'bist',
      label: 'BIST & TEFAS',
      critical: false,
      upstreams: 7,
    },
  ],
} as const;

export const LLM = {
  presets: 13,
  adapters: [
    'anthropic',
    'ollama',
    'openai_compat',
  ],
} as const;

export const TESTS = {
  suites: [
    {
      name: 'backend',
      tests: 3229,
      files: 147,
    },
    {
      name: 'mcp-server',
      tests: 28,
      files: 1,
    },
    {
      name: 'frontend',
      tests: 1031,
      files: 54,
    },
  ],
  total: 4288,
} as const;
