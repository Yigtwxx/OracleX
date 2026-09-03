'use client';

/**
 * Turning one alarm into the readings it should be judged against.
 *
 * Everything here goes through `queryClient.fetchQuery` rather than calling a
 * fetcher directly, which buys two things for free: a user already looking at
 * the funding board does not download it twice, and `staleTime` — set from the
 * registry's `minIntervalMs` — becomes the per-source poll floor, so the engine
 * needs no scheduler of its own. Two alarms on the same source share one
 * request.
 *
 * No decisions are made here. Guards on staleness, missing readings and
 * repeats all live in `evaluate.ts`; this module's job is to report what the
 * upstream said, including when it said nothing.
 */

import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/hooks/queries';
import {
  fetchChainAnomalies,
  fetchFearGreedIndex,
  fetchFundingRates,
  fetchLiquidations,
  fetchLiveEvents,
  fetchMarketOverview,
  fetchNehIndex,
  fetchNews,
  fetchPizzaIndex,
  fetchPolymarketMarket,
  fetchSymbolPrice,
} from '@/lib/api';
import { getAlarmSource } from './registry';
import { formatSourceValue } from './describe';
import type { Alarm, Reading } from './types';

/**
 * Compare a user-typed symbol against a board row.
 *
 * Symbols carry their venue here (`BINANCE:ETHUSDT`, `NASDAQ:AAPL`) while the
 * overview and funding boards list a bare base asset, so a literal comparison
 * would never match what the user typed into the chart.
 */
function normalizeSymbol(symbol: string): string {
  const bare = symbol.includes(':') ? symbol.split(':')[1] : symbol;
  return bare.toUpperCase().replace(/(USDT|USDC|USD)$/, '');
}

function symbolMatches(wanted: string, candidate: string): boolean {
  return normalizeSymbol(wanted) === normalizeSymbol(candidate);
}

function cached<T>(key: readonly unknown[], queryFn: () => Promise<T>, staleTime: number) {
  return queryClient.fetchQuery({ queryKey: key, queryFn, staleTime });
}

/**
 * Readings for one alarm.
 *
 * A level source yields exactly one; an event-shaped source yields one per item
 * still in the feed. Returning `[]` means "nothing to judge", which is not the
 * same as a reading of zero and never reaches the evaluator.
 */
export async function loadReadings(alarm: Alarm): Promise<Reading[]> {
  const source = getAlarmSource(alarm.sourceId);
  const ttl = source.minIntervalMs;
  const symbol = alarm.params.symbol?.trim() ?? '';

  switch (alarm.sourceId) {
    case 'price': {
      if (!symbol) return [];
      // 404 for an unresolvable symbol propagates as a throw and is reported by
      // the engine — better than a silent skip, which is how the old poller hid
      // the fact that equity alarms never fired at all.
      const data = await cached(queryKeys.symbolPrice(symbol), () => fetchSymbolPrice(symbol), ttl);
      return [
        {
          key: `price:${symbol}`,
          values: { price: data.price },
          stale: false,
          display: formatSourceValue('price', 'price', data.price),
        },
      ];
    }

    case 'change24h': {
      if (!symbol) return [];
      const overview = await cached(queryKeys.marketOverview, fetchMarketOverview, ttl);
      const row = overview.coins.find((coin) => symbolMatches(symbol, coin.symbol));
      if (!row) return [];
      return [
        {
          key: `change24h:${symbol}`,
          values: { change_24h: row.change_24h },
          stale: false,
          display: formatSourceValue('change24h', 'change_24h', row.change_24h),
        },
      ];
    }

    case 'btcDominance': {
      const overview = await cached(queryKeys.marketOverview, fetchMarketOverview, ttl);
      return [
        {
          key: 'btcDominance',
          values: { btc_dominance: overview.btc_dominance },
          stale: false,
          display: formatSourceValue('btcDominance', 'btc_dominance', overview.btc_dominance),
        },
      ];
    }

    case 'funding': {
      const rows = await cached(queryKeys.fundingRates, fetchFundingRates, ttl);
      const matching = symbol ? rows.filter((row) => symbolMatches(symbol, row.symbol)) : rows;
      return matching.map((row) => {
        // `rate` is a decimal upstream (0.0001); the board and the builder both
        // speak percent, so convert once here rather than in two places.
        const percent = row.rate * 100;
        return {
          key: symbol ? `funding:${row.symbol}` : `funding:${row.symbol}:${row.next_funding_time}`,
          // Without a symbol this alarm watches the whole board, and one
          // hysteresis latch cannot track thirty independent rates — so each
          // row/settlement pair becomes its own event instead.
          eventShaped: !symbol,
          values: {
            rate: percent,
            is_extreme: String(row.is_extreme),
            symbol: row.symbol,
          },
          stale: false,
          display: `${row.symbol} ${formatSourceValue('funding', 'rate', percent)}`,
        };
      });
    }

    case 'liquidation': {
      const rows = await cached(queryKeys.liquidations, fetchLiquidations, ttl);
      const side = alarm.params.side?.trim() ?? '';
      return rows
        .filter((row) => (symbol ? symbolMatches(symbol, row.symbol) : true))
        .filter((row) => (side ? row.side === side : true))
        .map((row) => ({
          key: `liq:${row.symbol}:${row.timestamp}:${row.amount_usd}`,
          eventShaped: true,
          values: { amount_usd: row.amount_usd, side: row.side, symbol: row.symbol },
          stale: false,
          display: `${row.symbol} ${row.side} ${formatSourceValue('liquidation', 'amount_usd', row.amount_usd)}`,
        }));
    }

    case 'pizza': {
      const data = await cached(queryKeys.pizzaIndex, fetchPizzaIndex, ttl);
      return [
        {
          key: 'pizza',
          values: { index: data.index, status: data.status },
          stale: data.stale,
          // `unavailable` / `insufficient_data` reach the evaluator as a status
          // rather than an exception: this endpoint never answers 503.
          status: data.status,
          display:
            data.index === null
              ? data.label
              : `${formatSourceValue('pizza', 'index', data.index)} · ${data.label}`,
        },
      ];
    }

    case 'neh': {
      const data = await cached(queryKeys.nehIndex, fetchNehIndex, ttl);
      return [
        {
          key: 'neh',
          values: { index: data.index, status: data.status },
          stale: data.stale,
          status: data.status,
          display:
            data.index === null
              ? data.label
              : `${formatSourceValue('neh', 'index', data.index)} · ${data.label}`,
        },
      ];
    }

    case 'feargreed': {
      const data = await cached(queryKeys.fearGreedIndex, fetchFearGreedIndex, ttl);
      return [
        {
          key: 'feargreed',
          values: { value: data.value },
          stale: false,
          display: `${data.value} · ${data.classification}`,
        },
      ];
    }

    case 'chainAnomaly': {
      const report = await cached(queryKeys.chainAnomalies, fetchChainAnomalies, ttl);
      const chain = alarm.params.chain?.trim().toLowerCase() ?? '';
      return report.anomalies
        .filter((anomaly) => (chain ? anomaly.chain.toLowerCase() === chain : true))
        .map((anomaly) => ({
          key: `anomaly:${anomaly.chain}:${anomaly.kind}:${report.as_of ?? ''}`,
          eventShaped: true,
          values: {
            severity: anomaly.severity,
            magnitude: anomaly.magnitude,
            chain: anomaly.chain,
          },
          stale: report.stale,
          display: `${anomaly.chain_name} — ${anomaly.text}`,
        }));
    }

    case 'news': {
      const assetType = alarm.params.assetType?.trim() || undefined;
      const items = await cached(queryKeys.news(assetType), () => fetchNews(assetType), ttl);
      return items
        .filter((item) => (symbol ? item.symbol && symbolMatches(symbol, item.symbol) : true))
        .map((item) => ({
          key: `news:${item.id}`,
          eventShaped: true,
          values: { title: item.title, summary: item.summary },
          stale: false,
          display: item.title,
        }));
    }

    case 'macroEvent': {
      const response = await cached(queryKeys.liveEvents, fetchLiveEvents, ttl);
      const impact = alarm.params.impact?.trim() ?? '';
      const now = Date.now();
      return (
        response.upcoming
          .filter((event) => (impact ? event.impact === impact : true))
          // A row the source scheduled for a day but not a time cannot support a
          // countdown; announcing it at midnight would be a guess.
          .filter((event) => event.time_confirmed)
          .map((event) => ({
            key: `event:${event.id}`,
            eventShaped: true,
            values: { minutesUntil: (Date.parse(event.starts_at) - now) / 60_000 },
            stale: response.stale,
            display: event.title,
          }))
      );
    }

    case 'polymarket': {
      const slug = alarm.params.slug?.trim() ?? '';
      if (!slug) return [];
      const detail = await cached(
        queryKeys.polymarketMarket(slug),
        () => fetchPolymarketMarket(slug),
        ttl
      );
      const { leading_price, drift_24h, leading_outcome } = detail.microstructure;
      // Probabilities and drift are both 0-1 upstream; the builder speaks
      // percent and points.
      const price = leading_price === null ? null : leading_price * 100;
      return [
        {
          key: `polymarket:${slug}`,
          values: {
            leading_price: price,
            drift_24h: drift_24h === null ? null : drift_24h * 100,
          },
          stale: false,
          display:
            price === null
              ? detail.facts.market.question
              : `${leading_outcome ?? 'Leading'} ${formatSourceValue('polymarket', 'leading_price', price)}`,
        },
      ];
    }
  }
}
