/**
 * The colour a company is already recognised by.
 *
 * Same principle as `assetIdentity`, one level further out: the hue names the
 * holding, never its direction. Coca-Cola is red on this board whether the
 * position was added or trimmed, exactly as bitcoin is orange either way.
 *
 * Two rules govern what is in here.
 *
 * Only brands whose colour is genuinely theirs. Apple's mark is monochrome and
 * Berkshire has no colour at all; inventing one for them would make the map a
 * palette, and a palette assigned by ticker is just a random colour with extra
 * steps. Anything absent falls through to the chart rotation, which is designed
 * for exactly that case.
 *
 * Tuned for this app's near-black surface, not copied from a brand book. Visa's
 * navy (#1A1F71) and UPS's brown (#351C15) are invisible on #0a0a0c, so what is
 * stored here is the brand's hue at a lightness that can be read on it. The
 * colour still has to identify the company at a glance, which a hue nobody can
 * see does not.
 *
 * Hex rather than Tailwind classes because these are data, not theme: the theme
 * has six chart colours and this is a lookup table of forty brands, none of
 * which belong in the design tokens.
 */

const BRAND_COLOR: Record<string, string> = {
  // Consumer
  KO: '#F5333F',
  PEP: '#2F8FD8',
  MCD: '#FFC72C',
  SBUX: '#17A673',
  NKE: '#F26B21',
  HD: '#F96302',
  LOW: '#3A7FCC',
  COST: '#E4444F',
  TGT: '#E03C3C',
  WMT: '#3B9AE1',
  KHC: '#E7484F',
  ABNB: '#FF5A5F',
  UBER: '#4BC28A',
  DIS: '#5A7BEE',
  NFLX: '#E5484D',
  SPOT: '#1DB954',

  // Financial
  AXP: '#7FB3E8',
  BAC: '#2E6BE6',
  V: '#6C77D8',
  MA: '#F79E1B',
  JPM: '#B08A4A',
  GS: '#5B9BD5',
  BRK: '#8FA3B8',
  PYPL: '#00A0DE',
  COIN: '#3B75FF',
  XYZ: '#00D632',
  HOOD: '#38E06A',

  // Technology
  NVDA: '#76B900',
  AMZN: '#FF9900',
  GOOGL: '#4285F4',
  GOOG: '#4285F4',
  MSFT: '#00A4EF',
  META: '#3B7DFF',
  AAPL: '#A9B4BD',
  TSLA: '#E82127',
  TSM: '#E8544B',
  ASML: '#3A87D8',
  AMD: '#F0553F',
  INTC: '#2E8FE0',
  ORCL: '#C74634',
  CRM: '#00A1E0',
  ADBE: '#FA4B41',
  IBM: '#4D8BFE',
  CSCO: '#049FD9',
  QCOM: '#5A74E8',
  SHOP: '#95BF47',
  PDD: '#E0473D',
  SNOW: '#29B5E8',

  // Industrial, energy, health
  CAT: '#FFCD11',
  DE: '#4CA33C',
  UPS: '#B4884D',
  BA: '#3F7BDE',
  XOM: '#F0353F',
  CVX: '#3E8BD0',
  JNJ: '#E0453C',
  LLY: '#E0453C',
  UNH: '#3E7FC7',
  PFE: '#3F8FE0',
  T: '#00A8E0',
  VZ: '#EE3B3B',
};

/** The company's own colour, or undefined when it has none worth claiming. */
export function brandColor(symbol: string | null | undefined): string | undefined {
  if (!symbol) return undefined;
  return BRAND_COLOR[symbol.toUpperCase()];
}

/**
 * Whether two colours are close enough that a reader would not call them apart.
 *
 * Plain RGB distance. It is a crude model of perception and the right one here:
 * the question is not which colour is prettier but whether two segments touching
 * each other read as one, and at this threshold anything that passes is visibly
 * a different hue. Brand colours collide — Coca-Cola red and Netflix red are the
 * same red — so something has to decide, and the bar's whole purpose is that its
 * segments are told apart.
 */
export function tooClose(a: string, b: string, threshold = 90): boolean {
  const parse = (hex: string): [number, number, number] => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  return Math.hypot(r1 - r2, g1 - g2, b1 - b2) < threshold;
}
