import { HEALTH } from '@/lib/generated/repo-facts';
import FigureFrame from './FigureFrame';

/**
 * The health categories, and which of them the terminal cannot do without.
 *
 * A table rather than a canvas, deliberately. There is no sequence here and no
 * direction — it is a list of things and a property of each — and DOM draws that
 * better than a canvas can while leaving it selectable and readable aloud.
 *
 * Critical is drawn as a filled mark and non-critical as a hollow one, rather
 * than as two colours. Colour would make the non-critical rows look degraded;
 * they are not, they are simply things you can lose without being lied to.
 */
export default function HealthFigure() {
  return (
    <FigureFrame
      eyebrow="Health registry"
      footnote={
        <>
          {HEALTH.upstreams} upstreams · {HEALTH.critical} critical
          <br />
          idle is a state, not a fault
        </>
      }
    >
      <ul className="space-y-1.5">
        {HEALTH.rows.map((row) => (
          <li key={row.key} className="flex items-center gap-2.5 font-mono text-2xs">
            <span
              aria-hidden="true"
              className={`h-[5px] w-[5px] shrink-0 ${
                row.critical ? 'bg-down' : 'border border-line-strong'
              }`}
            />
            <span className="flex-1 truncate text-fg-muted">{row.label}</span>
            <span className="tabnum text-fg-subtle">{row.upstreams}</span>
          </li>
        ))}
      </ul>
    </FigureFrame>
  );
}
