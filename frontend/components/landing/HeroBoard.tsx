/**
 * The right half of the hero: what the terminal actually has running.
 *
 * The hero's left column is a claim; this is the receipt. It reads as a module
 * manifest rather than a feature list because that is what the product is — a
 * board with these things wired into it — and because a mono table opposite a
 * 52px headline is the contrast the layout was missing.
 *
 * A surface earns a row, not a route. `alarms` is a control in the nav rather
 * than a page, and it is here because losing it would be losing something.
 * Elections is the opposite case: it is a panel on the macro board, so it is
 * named in that row rather than given one, because a manifest that promises a
 * module and delivers a panel is the kind of small lie the rest of this page is
 * arguing against.
 */
const MODULES: readonly { readonly id: string; readonly name: string; readonly detail: string }[] =
  [
    { id: '01', name: 'analysis', detail: 'evidence → report → review' },
    { id: '02', name: 'chat', detail: 'RAG vector memory' },
    { id: '03', name: 'live', detail: 'websocket feed, on-chain' },
    { id: '04', name: 'heatmap', detail: 'crypto + US equities' },
    { id: '05', name: 'macro', detail: 'calendar, elections, why' },
    { id: '06', name: 'ownership', detail: '13F positioning' },
    { id: '07', name: 'chains', detail: 'per-chain, anomalies' },
    { id: '08', name: 'markets', detail: 'prediction odds, sourced' },
    { id: '09', name: 'alarms', detail: 'conditions you define' },
    { id: '10', name: 'community', detail: 'posts, profiles, lists' },
  ];

export default function HeroBoard() {
  return (
    <div className="landing-note w-full max-w-sm p-5">
      <div className="mb-4 flex items-center gap-2.5">
        <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
          Board manifest
        </span>
        <span className="flex-1 border-t border-dashed border-line" />
        <span className="flex items-center gap-1.5 font-mono text-2xs text-up">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-up" />
          live
        </span>
      </div>

      <ul className="space-y-2.5">
        {MODULES.map((module) => (
          <li key={module.id} className="flex items-baseline gap-3 font-mono text-2xs">
            <span className="tabnum text-fg-subtle">{module.id}</span>
            <span className="w-[4.5rem] shrink-0 text-fg">{module.name}</span>
            <span className="truncate text-fg-subtle">{module.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
