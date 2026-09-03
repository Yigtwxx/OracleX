import { API } from '@/lib/generated/repo-facts';
import FigureFrame from './FigureFrame';

/**
 * The API surface, by verb.
 *
 * Bars rather than a table because the shape is the point: this is a read
 * surface with a small write surface attached, and a column of numbers makes
 * you work that out. Widths are set as a custom property and filled by CSS once
 * the section arrives, so there is no layout effect and nothing to measure.
 */
export default function SurfaceFigure() {
  return (
    <FigureFrame
      eyebrow="HTTP surface"
      footnote={
        <>
          {API.authRequired} of {API.operations} require auth · {API.routers} routers
          <br />
          {API.websockets.join(', ')} — a socket, so it carries no schema entry
        </>
      }
    >
      <ul className="space-y-2.5">
        {API.methods.map((row) => (
          <li key={row.method} className="flex items-center gap-3 font-mono text-2xs">
            <span className="w-[3.5rem] shrink-0 text-fg-subtle">{row.method}</span>
            <span className="h-[3px] flex-1 bg-line">
              <span
                className="landing-bar block h-full bg-fg-muted"
                style={{ '--w': `${(row.count / API.operations) * 100}%` } as React.CSSProperties}
              />
            </span>
            <span className="w-6 shrink-0 text-right tabnum text-fg">{row.count}</span>
          </li>
        ))}
      </ul>
    </FigureFrame>
  );
}
