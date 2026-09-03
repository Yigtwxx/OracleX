/**
 * Turning the market-note facts into the deterministic header above the prose.
 *
 * This layer exists because of one unit mismatch that would otherwise be a
 * silent bug. Every other figure crossing `lib/bist-api.ts` is a **fraction** —
 * `0.012` — and `formatPercent` multiplies by a hundred on the way out. The
 * market-note facts are **already percentage points**, because the backend
 * quantizes each reading to a bucket before it fingerprints the note, and the
 * sentence beside the header is rendered from those same bucketed values. Round
 * them a second time here and the header would disagree with the paragraph it
 * introduces, which is the one failure the whole cache design exists to avoid.
 * So this file has its own formatter and the bist-wide one is deliberately
 * unused.
 *
 * The rest is label and tone maps plus the chip builders. It lives in `lib/`
 * rather than in the components because this repo tests `lib/*.ts` and does not
 * test components — anything with a branch in it belongs on this side of the
 * line.
 */

import type {
  BistFundsMarketFacts,
  BistFundsMarketStance,
  BistMacroFacts,
  BistMacroStance,
  BistMarketFacts,
  BistMarketStance,
  BistPositioningFacts,
  BistPositioningStance,
} from '@/lib/bist-api';
import { EMPTY, formatNumber } from '@/lib/bist-format';

/**
 * A figure that is already in percentage points.
 *
 * Turkish writes the sign before the percent sign and the percent sign before
 * the number: `+%1,2`. Not `formatPercent`, which would multiply by a hundred —
 * see the note at the top of this file.
 */
export function formatPoints(
  value: number | null | undefined,
  options: { sign?: boolean; decimals?: number } = {}
): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return EMPTY;
  const { sign = false, decimals = 1 } = options;
  const lead = sign && value > 0 ? '+' : '';
  return `${lead}%${formatNumber(value, decimals)}`;
}

// ── Equities ───────────────────────────────────────────────────────────────

/**
 * The stance as a reader would say it.
 *
 * "Dar" rather than "zayıf": the point is not that the move was small — a narrow
 * rally can be a large one — but that few names took part in it.
 */
export const MARKET_STANCE_LABEL: Record<BistMarketStance, string> = {
  narrow_rally: 'Dar yükseliş',
  broad_rally: 'Geniş yükseliş',
  narrow_selloff: 'Dar satış',
  broad_selloff: 'Geniş satış',
  mixed: 'Karışık seyir',
};

/**
 * Tone follows the direction of the index, not whether the reading is
 * comfortable. A narrow rally is still a rally, and colouring it red because it
 * is fragile would state a view the header is not entitled to.
 */
export const MARKET_STANCE_TONE: Record<BistMarketStance, string> = {
  narrow_rally: 'text-up',
  broad_rally: 'text-up',
  narrow_selloff: 'text-down',
  broad_selloff: 'text-down',
  mixed: 'text-fg-muted',
};

export interface Chip {
  /** What the figure is, for the tooltip. */
  title: string;
  text: string;
}

/**
 * The readings worth a glance, in the order a professional reaches for them.
 *
 * Deliberately short. This is the line that survives when the model does not
 * answer, so it carries what the table below genuinely cannot show — breadth
 * against the index, turnover concentration, the real policy rate — and not a
 * summary of the columns that are already on screen.
 */
export function marketChips(facts: BistMarketFacts): Chip[] {
  const chips: Chip[] = [];
  const { index, breadth, sentiment, concentration, macro, valuation } = facts;

  if (index.change_pct !== null) {
    chips.push({
      title: `${index.code} bugün`,
      text: `${index.code} ${formatPoints(index.change_pct, { sign: true })}`,
    });
  }

  chips.push({
    title: 'Yükselen / düşen hisse sayısı',
    text: `${breadth.advancers}↑ / ${breadth.decliners}↓`,
  });

  if (concentration.top5_turnover_pct !== null) {
    chips.push({
      title: 'Günün işlem hacminde ilk beş hissenin payı',
      text: `ilk 5 ${formatPoints(concentration.top5_turnover_pct)}`,
    });
  }

  if (sentiment && sentiment.score !== null) {
    chips.push({
      title: `${sentiment.measured} hisseden hesaplanan korku ve açgözlülük endeksi`,
      text: `duyarlılık ${formatNumber(sentiment.score, 0)} ${sentiment.label}`,
    });
  }

  // The year in purchasing-power terms, which is the reading this realm exists
  // to surface and the one no column on the screener carries for the index.
  if (index.year_real_pct !== null) {
    chips.push({
      title: `${index.code} son bir yıl, enflasyona göre reel`,
      text: `1Y reel ${formatPoints(index.year_real_pct, { sign: true })}`,
    });
  }

  if (valuation.median_pe !== null) {
    chips.push({
      title: `${index.code} medyan F/K — zarar edenler hariç`,
      text: `F/K ${formatNumber(valuation.median_pe, 1)}`,
    });
  }

  if (macro?.real_policy_rate_pct != null) {
    chips.push({
      title: 'Politika faizinin enflasyona göre reel karşılığı (Fisher)',
      text: `reel faiz ${formatPoints(macro.real_policy_rate_pct, { sign: true })}`,
    });
  }

  return chips;
}

// ── Funds ──────────────────────────────────────────────────────────────────

export const FUND_STANCE_LABEL: Record<BistFundsMarketStance, string> = {
  beating_inflation: 'Çoğunluk enflasyonu yendi',
  losing_to_inflation: 'Çoğunluk enflasyona yenildi',
  split: 'Bölünmüş tablo',
};

export const FUND_STANCE_TONE: Record<BistFundsMarketStance, string> = {
  beating_inflation: 'text-up',
  losing_to_inflation: 'text-down',
  split: 'text-fg-muted',
};

/**
 * What a return table sorted by performance cannot say.
 *
 * The median rather than the leader, the percentile spread rather than the top
 * of it, and the count of funds that printed a lira gain their holder did not
 * keep. Each of these is a fact about the set; the table below is a fact about
 * its rows.
 */
export function fundChips(facts: BistFundsMarketFacts): Chip[] {
  const chips: Chip[] = [];
  const { spread, inflation, risk_free: riskFree } = facts;

  if (facts.median_real_pct !== null) {
    chips.push({
      title: `${facts.measured} fonun medyan 1 yıllık reel getirisi`,
      text: `medyan 1Y reel ${formatPoints(facts.median_real_pct, { sign: true })}`,
    });
  } else if (facts.median_nominal_pct !== null) {
    chips.push({
      title: 'Medyan 1 yıllık nominal getiri — enflasyon serisi alınamadı',
      text: `medyan 1Y ${formatPoints(facts.median_nominal_pct, { sign: true })} nominal`,
    });
  }

  if (inflation.measured > 0) {
    chips.push({
      title: 'Son bir yılda enflasyonu yenen fon sayısı',
      text: `${inflation.beat_count}/${inflation.measured} enflasyonu yendi`,
    });
  }

  if (inflation.nominal_gain_real_loss > 0) {
    chips.push({
      title: 'Lirada kazanıp alım gücünde kaybeden fon sayısı',
      text: `${inflation.nominal_gain_real_loss} fon lirada kazandı, reelde kaybetti`,
    });
  }

  // The gap between the tenth and ninetieth percentile — whether picking the
  // fund mattered more than picking the category.
  if (spread.width_pct !== null) {
    chips.push({
      title: '10. ve 90. yüzdelik reel getiri arasındaki fark',
      text: `dağılım ${formatPoints(spread.width_pct)}`,
    });
  }

  if (riskFree.rate_pct !== null) {
    chips.push({
      title:
        riskFree.source === 'money_market_median'
          ? 'Para piyasası fonlarının medyan yıllık getirisinden türetildi, TCMB politika faizinden değil'
          : 'Risksiz faiz',
      text: `risksiz faiz ${formatPoints(riskFree.rate_pct)}`,
    });
  }

  return chips;
}

// ── Positioning ────────────────────────────────────────────────────────────

/**
 * The stance names the behaviour, not the direction.
 *
 * "Kalabalık zirveye yakın" would describe where the busiest names are; the read
 * is that they are *higher than the board they came from*, which is a different
 * claim and the only one the four panels cannot make between them.
 */
export const POSITIONING_STANCE_LABEL: Record<BistPositioningStance, string> = {
  chasing_strength: 'Kalabalık yükseleni kovalıyor',
  bottom_fishing: 'Kalabalık düşene giriyor',
  dispersed: 'Kalabalık dağınık',
};

/**
 * Neither behaviour is good or bad, so neither gets a direction colour.
 *
 * Chasing strength is not a rally and bottom fishing is not a decline — they are
 * descriptions of where unusual volume went. Painting the first green would
 * state a view the header is not entitled to, which is the same rule
 * `MARKET_STANCE_TONE` follows from the opposite direction: it colours by the
 * index because there the direction is the reading.
 */
export const POSITIONING_STANCE_TONE: Record<BistPositioningStance, string> = {
  chasing_strength: 'text-fg',
  bottom_fishing: 'text-fg',
  dispersed: 'text-fg-muted',
};

/**
 * What four panels drawing the same rows cannot say between them.
 *
 * The crowd's position in its own year against the board's, the float it is
 * happening in, and how much of the board's whole crowding sits in one sector.
 * Each is a fact about the set; the panels below are facts about its rows.
 */
export function positioningChips(facts: BistPositioningFacts): Chip[] {
  const chips: Chip[] = [];
  const { board, crowd, range, sectors, futures } = facts;

  if (crowd.median_range_pct !== null && crowd.board_median_range_pct !== null) {
    chips.push({
      title: `En kalabalık ${crowd.cohort} ismin 52 haftalık aralıktaki medyan konumu, borsanın medyanına karşı`,
      text: `kalabalık ${formatPoints(crowd.median_range_pct)} · borsa ${formatPoints(crowd.board_median_range_pct)}`,
    });
  }

  if (crowd.median_free_float_pct !== null && board.median_free_float_pct !== null) {
    chips.push({
      title:
        'Kalabalık kohortun medyan halka açıklığı, borsanın medyanına karşı — aynı akış dar bir halka açıklığı çok daha fazla oynatır',
      text: `halka açıklık ${formatPoints(crowd.median_free_float_pct)} · borsa ${formatPoints(board.median_free_float_pct)}`,
    });
  }

  chips.push({
    title: `${board.total} hissenin kaçı ölçülebilir bir kalabalıklık skoru taşıyor`,
    text: `${board.scored}/${board.total} skorlandı`,
  });

  if (range.near_high_pct !== null) {
    chips.push({
      title: `Yıllık zirvesinin %${formatNumber(range.near_extreme_pct, 0)} yakınındaki hisselerin payı`,
      text: `zirveye yakın ${formatPoints(range.near_high_pct)}`,
    });
  }

  // One sector carrying most of the board's crowding is the finding, not a
  // footnote on it — the treemap shows which sector is heaviest and cannot show
  // that it is the whole ranking.
  const top = sectors[0];
  if (top && top.share_pct !== null) {
    chips.push({
      title: `${top.sector} sektörünün, borsanın toplam kalabalıklık skorundaki payı`,
      text: `${top.sector} ${formatPoints(top.share_pct)}`,
    });
  }

  if (futures && futures.growth_pct !== null) {
    chips.push({
      title: `${futures.covered} dayanak varlıkta vadeli açık pozisyonun düne göre değişimi`,
      text: `açık pozisyon ${formatPoints(futures.growth_pct, { sign: true })}`,
    });
  }

  return chips;
}

/**
 * Whether the panel should draw at all.
 *
 * Null facts mean the board could not be read, which is not the same as a quiet
 * market — and a panel that rendered an empty header for it would be claiming
 * the second. The AI paragraph has its own three-state contract in
 * `components/ui/AiNote.tsx`; this only governs the frame around it.
 */
export function hasMarketRead(
  facts: BistMarketFacts | BistFundsMarketFacts | BistPositioningFacts | null | undefined
): boolean {
  return !!facts;
}

// ── Macro ──────────────────────────────────────────────────────────────────

/**
 * The stance is the sign of the real policy rate, said as a fact.
 *
 * Not "sıkı" or "gevşek": whether a positive real rate is restrictive is a
 * judgement about the economy, and the header is only entitled to the
 * arithmetic — which is Fisher's, done server-side.
 */
export const MACRO_STANCE_LABEL: Record<BistMacroStance, string> = {
  real_positive: 'Reel faiz pozitif',
  real_near_zero: 'Reel faiz sıfıra yakın',
  real_negative: 'Reel faiz negatif',
};

/** Tone follows the sign, as it does for every signed figure on this realm. */
export const MACRO_STANCE_TONE: Record<BistMacroStance, string> = {
  real_positive: 'text-up',
  real_near_zero: 'text-fg-muted',
  real_negative: 'text-down',
};

/**
 * The crossings the tiles cannot show, in the order a rates desk reaches for
 * them: the rate net of inflation, the rate net of the currency's loss,
 * producer against consumer prices, the pace inside the year, and how many
 * measures the exchange filed this week. Not the tiles themselves.
 */
export function macroChips(facts: BistMacroFacts): Chip[] {
  const chips: Chip[] = [];
  const { rates, fx, prices, measures } = facts;

  if (rates.real_policy_pct !== null) {
    chips.push({
      title: 'Politika faizinin enflasyondan arındırılmış hâli — Fisher ilişkisiyle, çıkarma değil',
      text: `reel faiz ${formatPoints(rates.real_policy_pct, { sign: true })}`,
    });
  }

  if (fx.change_12m_pct !== null) {
    chips.push({
      title: 'Liranın dolara karşı 12 aylık kaybı',
      text: `₺ 12 ay ${formatPoints(fx.change_12m_pct, { sign: true })}`,
    });
  }

  if (fx.carry_12m_pct !== null) {
    chips.push({
      title: 'Politika faizi eksi 12 aylık kur kaybı — gösterge, gerçekleşmiş getiri değil',
      text: `faiz − kur ${formatPoints(fx.carry_12m_pct, { sign: true })}`,
    });
  }

  if (rates.ppi_cpi_gap_pct !== null) {
    chips.push({
      title: 'Üretici enflasyonu eksi tüketici enflasyonu — pozitifse henüz gelmemiş baskı',
      text: `ÜFE − TÜFE ${formatPoints(rates.ppi_cpi_gap_pct, { sign: true })}`,
    });
  }

  if (prices && prices.three_month_annualized_pct !== null) {
    chips.push({
      title: 'TÜFE endeksinin son üç aylık değişimi, yıllıklandırılmış',
      text: `3 ay yıllık ${formatPoints(prices.three_month_annualized_pct)}`,
    });
  }

  // A count of zero is a calm week and worth the chip; an absent tape is not
  // a calm week and gets nothing.
  if (measures) {
    chips.push({
      title:
        'Son günlerde KAP üzerinden duyurulan borsa tedbirleri (devre kesici, açığa satış yasağı, brüt takas…)',
      text: `${measures.window_days} günde ${measures.total} tedbir`,
    });
  }

  return chips;
}
