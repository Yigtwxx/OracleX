import type { ReactNode } from 'react';

interface BistPageShellProps {
  title: string;
  /** One line under the title — what this board answers. */
  description: string;
  /** Right-aligned slot in the header: refresh state, filters, as-of stamp. */
  action?: ReactNode;
  /**
   * A line of board-wide readings under the header.
   *
   * Under the header rather than in the page body because it is context for
   * everything below rather than one more panel among them — the same place
   * `MarketRibbon` sits on the crypto realm's Home.
   *
   * Full width rather than inside the title column: the readings are a long
   * line of small figures and the right-hand controls were taking three
   * hundred pixels off it, which wrapped the last two onto a second row with
   * the first still half empty.
   */
  ribbon?: ReactNode;
  /**
   * Show the delayed-data badge.
   *
   * Every price on this realm comes from Borsa İstanbul at least fifteen
   * minutes late, and a terminal that renders a delayed number without saying
   * so is worse than one that shows nothing. Opt-in rather than always-on so a
   * board built purely from fund NAVs or KAP filings — neither of which is a
   * live quote — does not carry a caveat that does not apply to it.
   */
  delayed?: boolean;
  children: ReactNode;
}

/**
 * The frame every `/bist` page sits in: scroll container, centred column,
 * page header.
 *
 * Matches the global realm's page layout (see `MacroPage`) on purpose — the
 * realms differ in what they show, not in how a page is built.
 */
export default function BistPageShell({
  title,
  description,
  action,
  ribbon,
  delayed = false,
  children,
}: BistPageShellProps) {
  return (
    // `lang="tr"` is load-bearing, not metadata. CSS `text-transform:
    // uppercase` is language-sensitive, and without this the `.label` class
    // renders "1Y GETİRİ" as "1Y GETIRI" — the browser applies the default
    // Latin rule and turns a dotted `i` into a dotless `I`, which is a
    // different letter in Turkish. Every column header on this realm is
    // uppercased by CSS, so the whole subtree carries the tag.
    <div lang="tr" className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="mx-auto max-w-[1600px] space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-fg">{title}</h1>
            <p className="text-base text-fg-muted">{description}</p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {delayed && (
              <span
                title="Borsa İstanbul kaynaklı veriler en az 15 dakika gecikmelidir"
                className="rounded border border-line px-1.5 py-0.5 text-2xs uppercase tracking-wide text-fg-subtle"
              >
                15 dk gecikmeli
              </span>
            )}
            {action}
          </div>
        </div>

        {ribbon && <div className="-mt-2">{ribbon}</div>}

        {children}
      </div>
    </div>
  );
}
