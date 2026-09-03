'use client';

import Link from 'next/link';

import { BOARD_FUNDS, BOARD_WINDOW } from '@/lib/borsa/queries';
import {
  useBistFund,
  useBistFunds,
  useBistKap,
  useBistOverview,
  useBistPositioning,
} from '@/hooks/useBist';
import {
  EMPTY,
  formatCompactTry,
  formatNumber,
  formatPercent,
  formatRelative,
  formatSignedPercent,
} from '@/lib/bist-format';
import DeflationChart from './DeflationChart';
import FlipFigure from './FlipFigure';
import SectorStrip from './SectorStrip';

/**
 * The live half of the BIST product page.
 *
 * Every block here has a designed fall-back, and that is not defensive
 * programming — it is the marketing group's contract. `/` is required to render
 * with the backend down, no page in this group has ever fetched anything, and
 * this is the first that does. So the page's argument, typography and structure
 * are static, and the data decorates them: a block with nothing to show says so
 * in one quiet line rather than collapsing or spinning forever.
 *
 * A loading block draws its own shape rather than a centred "Yükleniyor…".
 * Three lines of grey text under a hero is a page that has not arrived; a
 * skeleton of the right height is a page whose figures have not.
 */

function Section({
  eyebrow,
  title,
  lede,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  lede?: React.ReactNode;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="borsa-section borsa-row">
      <div className="borsa-section-head">
        <div className="borsa-section-title">
          <p className="borsa-label">{eyebrow}</p>
          <h2 className="borsa-display mt-3 text-3xl sm:text-4xl">{title}</h2>
        </div>
        {lede && <p className="borsa-section-lede">{lede}</p>}
      </div>
      {children}
      {action && <div className="mt-8">{action}</div>}
    </section>
  );
}

/** A block that has failed, in one line, in the page's own voice. */
function Quiet({ children }: { children: React.ReactNode }) {
  return <p className="borsa-quiet">{children}</p>;
}

/** The block's own shape, held while its figures are in flight. */
function Skeleton({ rows = 6, tall = false }: { rows?: number; tall?: boolean }) {
  return (
    <div className="borsa-skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <span
          key={index}
          className="borsa-skeleton-row"
          data-tall={tall ? '' : undefined}
          style={{ ['--i' as string]: index }}
        />
      ))}
    </div>
  );
}

function MoreLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="borsa-more">
      {children}
      <span aria-hidden="true">→</span>
    </Link>
  );
}

// ── The chart the page exists for ──────────────────────────────────────────

/**
 * The claim, made about the board rather than about one fund.
 *
 * This is the section that turns the hero from an anecdote into a measurement,
 * and it is deliberately the second thing on the page: a reader who accepts it
 * has accepted the product's whole premise before meeting a single feature.
 */
export function LiveDeflation() {
  const { data, isLoading } = useBistFunds(BOARD_FUNDS);
  const funds = data?.funds ?? [];
  const inflation = data?.real_return?.inflation_yoy ?? null;
  const deflatable = !!data?.real_return?.deflatable_windows.includes(BOARD_WINDOW);
  const summary = data?.real_loss;

  return (
    <Section
      eyebrow="TEFAS · son 1 yıl · yılın en çok kazandıranları"
      title="Aynı liste, ikinci okumasıyla"
      lede={
        summary && summary.count > 0 ? (
          <>
            Sıralama değişmedi — her satıra ikinci bir uç eklendi. Sağdaki nokta her yerde yazan
            rakam, soldaki cebinde kalan. Aradaki mesafe geçen yılın enflasyonu; ölçülebilen{' '}
            {summary.measured} fondan {summary.count} tanesi bu mesafenin yanlış tarafında kaldı.
          </>
        ) : (
          <>
            Sıralama değişmedi — her satıra ikinci bir uç eklendi. Sağdaki nokta her yerde yazan
            rakam, soldaki cebinde kalan. Aradaki mesafe geçen yılın enflasyonu.
          </>
        )
      }
      action={<MoreLink href="/bist/fonlar">Bin fonu bu iki uçla tara</MoreLink>}
    >
      {isLoading && funds.length === 0 ? (
        <Skeleton rows={8} />
      ) : !deflatable || funds.length === 0 ? (
        <Quiet>
          Bu dönem için enflasyon serisi yok; getiriler reel karşılığıyla birlikte gösterilemiyor.
        </Quiet>
      ) : (
        <DeflationChart funds={funds} window={BOARD_WINDOW} inflation={inflation} />
      )}
    </Section>
  );
}

// ── The exchange itself ────────────────────────────────────────────────────

/** Where the money actually is, today, and what a year of it was worth. */
export function LiveMarket() {
  const { data, isLoading } = useBistOverview();
  const xu100 = data?.indices.find((index) => index.code === 'XU100');
  const inflation = data?.macro?.inflation_yoy ?? null;

  // The index read the way the page reads a fund. `perf_1y` and the annual CPI
  // cover the same window, which is the only reason this deflation is honest —
  // a daily change deflated by an annual rate would be arithmetic theatre.
  const nominal1y = xu100?.perf_1y ?? null;
  const real1y =
    nominal1y !== null && inflation !== null ? (1 + nominal1y) / (1 + inflation) - 1 : null;

  const breadth = data?.breadth;
  const advancers = breadth?.advancers ?? 0;
  const decliners = breadth?.decliners ?? 0;
  const unchanged = breadth?.unchanged ?? 0;

  return (
    <Section
      eyebrow="Borsa İstanbul · 15 dk gecikmeli"
      title="Endeks de aynı hesaba tabi"
      lede="Bir yılda BIST 100 ne kazandırdı, o yılın enflasyonundan sonra ne kaldı. Altındaki bant, o değerin hangi sektörlerde durduğunu piyasa değeri payıyla gösterir."
      action={<MoreLink href="/bist/hisseler">Hisse tablosunu aç</MoreLink>}
    >
      {isLoading && !data ? (
        <Skeleton rows={4} tall />
      ) : !data ? (
        <Quiet>Piyasa verisi şu anda alınamıyor.</Quiet>
      ) : (
        <>
          <div className="borsa-index">
            <div className="borsa-index-cell">
              <p className="borsa-label">XU100</p>
              <p className="borsa-figure borsa-index-value">
                {formatNumber(xu100?.value ?? null, 0)}
              </p>
              <p
                className="borsa-figure borsa-index-change"
                data-down={(xu100?.change_pct ?? 0) < 0 ? '' : undefined}
                data-flat={!xu100?.change_pct ? '' : undefined}
              >
                {formatSignedPercent(xu100?.change_pct ?? null)} bugün
              </p>
            </div>

            <div className="borsa-index-cell">
              <p className="borsa-label">1 yıl</p>
              {real1y !== null && nominal1y !== null ? (
                <FlipFigure
                  className="borsa-index-value borsa-figure"
                  from={formatSignedPercent(nominal1y)}
                  to={formatSignedPercent(real1y)}
                  fromColor="var(--borsa-nominal)"
                  toColor={real1y >= 0 ? 'var(--borsa-real-gain)' : 'var(--borsa-real-loss)'}
                  label={`Bir yıllık reel getiri ${formatSignedPercent(real1y)}`}
                />
              ) : (
                <p className="borsa-figure borsa-index-value">{formatSignedPercent(nominal1y)}</p>
              )}
              <p className="borsa-index-note">
                {real1y !== null
                  ? `nominal ${formatSignedPercent(nominal1y)} · TÜFE ${formatPercent(inflation)}`
                  : 'nominal — enflasyon serisi yok'}
              </p>
            </div>

            <div className="borsa-index-cell borsa-index-breadth">
              <p className="borsa-label">Yükselen / düşen</p>
              <p className="borsa-figure borsa-index-value">
                {advancers}
                <span className="borsa-index-slash"> / </span>
                {decliners}
              </p>
              <span className="borsa-breadth" aria-hidden="true">
                <span className="borsa-breadth-up" style={{ flexGrow: advancers || 1 }} />
                <span className="borsa-breadth-flat" style={{ flexGrow: unchanged }} />
                <span className="borsa-breadth-down" style={{ flexGrow: decliners || 1 }} />
              </span>
              <p className="borsa-index-note">{breadth?.total ?? 0} hisse</p>
            </div>
          </div>

          <SectorStrip sectors={data.sectors} />
        </>
      )}
    </Section>
  );
}

// ── Positioning ────────────────────────────────────────────────────────────

/**
 * Published positioning, not a guess about it.
 *
 * The row that used to sit here was a paragraph claiming the terminal measures
 * crowding. This is the measurement: unusual volume against a tight float, for
 * the six names where that ratio is highest right now.
 */
export function LivePositioning() {
  const { data, isLoading } = useBistPositioning(12);
  const rows = (data?.crowded ?? []).filter((row) => row.crowding !== null).slice(0, 6);
  const peak = rows.length > 0 ? Math.max(...rows.map((row) => row.crowding ?? 0)) : 1;

  return (
    <Section
      eyebrow="Konumlanma"
      title="Kimin nerede durduğu, tahmin değil ölçüm"
      lede="Halka açıklık oranı, nispi hacim, yıllık aralıktaki konum ve VİOP açık pozisyonu. Dar halka açıklığa binen olağandışı hacim, fiyat henüz söylemeden görünür."
      action={<MoreLink href="/bist/akilli-para">Konumlanma tablosunu aç</MoreLink>}
    >
      {isLoading && rows.length === 0 ? (
        <Skeleton rows={6} />
      ) : rows.length === 0 ? (
        <Quiet>Konumlanma verisi şu anda alınamıyor.</Quiet>
      ) : (
        <ul className="borsa-crowd">
          {rows.map((row) => (
            <li key={row.ticker} className="borsa-crowd-row">
              <span className="borsa-figure borsa-crowd-ticker">{row.ticker}</span>
              <span className="borsa-crowd-name">{row.name}</span>
              <span className="borsa-crowd-track" aria-hidden="true">
                <span
                  className="borsa-crowd-bar"
                  style={{ width: `${Math.round(((row.crowding ?? 0) / (peak || 1)) * 100)}%` }}
                />
              </span>
              <span className="borsa-crowd-stats">
                <span className="borsa-figure">
                  {row.relative_volume !== null
                    ? `${formatNumber(row.relative_volume, 1)}×`
                    : EMPTY}
                </span>
                <span className="borsa-crowd-stat-label">hacim</span>
                <span className="borsa-figure">{formatPercent(row.free_float_pct)}</span>
                <span className="borsa-crowd-stat-label">halka açık</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ── Risk behind a return ───────────────────────────────────────────────────

/**
 * What the ranking hides, on the fund the hero already named.
 *
 * No extra list request: the code comes from the same `real_loss` summary the
 * hero reads, and only the one fund's detail is fetched.
 */
export function LiveFundRisk() {
  const { data: funds } = useBistFunds(BOARD_FUNDS);
  const code = funds?.real_loss?.example?.code ?? null;
  const { data, isLoading } = useBistFund(code);
  const metrics = data?.metrics;

  const cells: { label: string; value: string; note: string }[] = metrics
    ? [
        {
          label: 'Sharpe',
          value: metrics.sharpe !== null ? formatNumber(metrics.sharpe, 2) : EMPTY,
          note: 'birim riske düşen getiri',
        },
        {
          label: 'Maks. düşüş',
          value: formatPercent(metrics.max_drawdown),
          note: 'tepe noktasından dibe',
        },
        {
          label: 'Toparlanma',
          value: metrics.recovery_days !== null ? `${metrics.recovery_days} gün` : 'toparlanmadı',
          note: 'dipten eski tepeye',
        },
        {
          label: 'Volatilite',
          value: formatPercent(metrics.volatility),
          note: 'yıllıklandırılmış',
        },
      ]
    : [];

  return (
    <Section
      eyebrow="Fon"
      title="Getiri sıralaması bir fonu anlatmaz"
      lede="TEFAS’taki bin fonu Sharpe, Sortino, maksimum düşüş, toparlanma süresi ve fona giren parayla birlikte tarıyoruz. Altı ayda üç haneli getiri yapan bir fon, bunu sahibinin oturamayacağı bir düşüşle yapmış olabilir; sıralamanın tepesinde bu görünmez."
      action={<MoreLink href="/bist/fonlar">Fon tarayıcısını aç</MoreLink>}
    >
      {isLoading || (!metrics && code) ? (
        <Skeleton rows={4} />
      ) : !metrics ? (
        <Quiet>Fon risk ölçümleri şu anda alınamıyor.</Quiet>
      ) : (
        <>
          <p className="borsa-metrics-head">
            <span className="borsa-figure">{data?.code}</span>
            <span className="borsa-metrics-title">{data?.title}</span>
          </p>
          <dl className="borsa-metrics">
            {cells.map((cell) => (
              <div key={cell.label} className="borsa-metric">
                <dt className="borsa-label">{cell.label}</dt>
                <dd className="borsa-figure borsa-metric-value">{cell.value}</dd>
                <dd className="borsa-metric-note">{cell.note}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </Section>
  );
}

// ── The disclosure tape ────────────────────────────────────────────────────

/**
 * KAP, deduplicated and honest about its own age.
 *
 * The exchange's own circuit-breaker notices arrive under one company name and
 * one title dozens of times a session, so an unfiltered six-row window is four
 * copies of the same line. And this block used to be titled "just came in"
 * above rows stamped four weeks old — the proof contradicting the claim. The
 * freshness is now stated from the data instead of asserted in the heading.
 */
export function LiveKapTape() {
  const { data, isLoading } = useBistKap({ limit: 30 });

  const seen = new Set<string>();
  const rows = (data?.disclosures ?? [])
    .filter((item) => {
      const key = `${item.company}|${item.title}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 7);

  const newest = rows[0]?.published_at ?? null;

  return (
    <Section
      eyebrow={newest ? `KAP · son bildirim ${formatRelative(newest)}` : 'KAP'}
      title="Şirketlerden gelen her bildirim"
      lede="Özel durum açıklamaları, temettü ve bilanço takvimi, devre kesici ve brüt takas duyuruları. Açığa satış yasağı gelen bir hisseyi haberden değil, akıştan öğrenirsin."
      action={<MoreLink href="/bist/kap">Bildirim akışını aç</MoreLink>}
    >
      {isLoading && rows.length === 0 ? (
        <Skeleton rows={7} />
      ) : rows.length === 0 ? (
        <Quiet>Bildirim akışı şu anda alınamıyor.</Quiet>
      ) : (
        <ul className="borsa-tape">
          {rows.map((item, index) => (
            <li key={item.index} className="borsa-tape-row" style={{ ['--i' as string]: index }}>
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="borsa-tape-link"
              >
                <span className="borsa-figure borsa-tape-ticker">{item.ticker || '—'}</span>
                <span className="borsa-tape-body">
                  <span className="borsa-tape-title">{item.title}</span>
                  <span className="borsa-tape-company">{item.company}</span>
                </span>
                <span className="borsa-label borsa-tape-time">
                  {formatRelative(item.published_at)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ── Coverage ───────────────────────────────────────────────────────────────

/** Market capitalisation covered, as a single line under the fund table. */
export function CoverageLine() {
  const { data } = useBistOverview();
  const { data: funds } = useBistFunds(BOARD_FUNDS);
  if (!data && !funds) return null;

  const totalCap = (data?.sectors ?? []).reduce((sum, sector) => sum + sector.market_cap, 0);

  return (
    <p className="borsa-label borsa-coverage">
      {data ? `${data.breadth.total} hisse` : EMPTY}
      {totalCap > 0 && ` · ${formatCompactTry(totalCap)} piyasa değeri`}
      {funds ? ` · ${funds.total} TEFAS fonu` : ''}
      {data?.macro?.inflation_yoy != null &&
        ` · yıllık TÜFE ${formatPercent(data.macro.inflation_yoy)}`}
    </p>
  );
}
