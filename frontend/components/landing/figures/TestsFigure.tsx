import { TESTS } from '@/lib/generated/repo-facts';
import FigureFrame from './FigureFrame';

/**
 * What has to pass, counted by the runners rather than by hand.
 *
 * These are the numbers that drifted worst before this file existed — the
 * frontend suite was reported seventy tests short for months, because someone
 * had counted `it(` and there are eleven parametrised tables it never saw. They
 * now come from the collectors, which is the only reason they are on the page.
 */
export default function TestsFigure() {
  return (
    <FigureFrame eyebrow="Test suites" footnote={<>collected, not counted by hand</>}>
      <ul className="space-y-2">
        {TESTS.suites.map((suite) => (
          <li key={suite.name} className="flex items-baseline gap-2.5 font-mono text-2xs">
            <span className="flex-1 truncate text-fg-muted">{suite.name}</span>
            <span className="tabnum text-fg">{suite.tests}</span>
            <span className="w-12 shrink-0 text-right tabnum text-fg-subtle">
              {suite.files} files
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex items-baseline gap-2.5 border-t border-dashed border-line pt-3 font-mono text-2xs">
        <span className="flex-1 text-fg-subtle">total</span>
        <span className="tabnum font-semibold text-fg">{TESTS.total}</span>
      </div>
    </FigureFrame>
  );
}
