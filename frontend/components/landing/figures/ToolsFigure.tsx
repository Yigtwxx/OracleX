import { MCP } from '@/lib/generated/repo-facts';
import FigureFrame from './FigureFrame';

/**
 * Which way a tool's candle points.
 *
 * A hash of the name, not `Math.random`. These render on the server and hydrate
 * on the client, and a random draw would disagree across that boundary — a
 * hydration mismatch on the one page whose entire argument is that its numbers
 * can be checked. Being deterministic also means the figure looks the same on
 * every visit, which is what makes it a diagram rather than a lava lamp.
 */
function risesFor(name: string): boolean {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return (hash & 1) === 0;
}

/**
 * Every MCP tool, as a mark, grouped the way the server groups them.
 *
 * Marks rather than names: thirty function names in a three-hundred-pixel rail
 * is a wall, and the claim being made is about the size and shape of the tool
 * list rather than about any one entry. The group labels carry the meaning; the
 * marks carry the count.
 */
export default function ToolsFigure() {
  return (
    <FigureFrame eyebrow="MCP tools" footnote={<>{MCP.total} tools · {MCP.groups.length} groups</>}>
      <ul className="space-y-3">
        {MCP.groups.map((group) => (
          <li key={group.label}>
            <div className="flex items-baseline justify-between gap-2 font-mono text-2xs">
              <span className="truncate text-fg-muted">{group.label}</span>
              <span className="tabnum text-fg-subtle">{group.tools.length}</span>
            </div>
            <div className="mt-1.5 flex items-end gap-1">
              {group.tools.map((tool) => (
                <span
                  key={tool}
                  title={tool}
                  className="relative block h-[11px] w-1"
                  aria-hidden="true"
                >
                  <span
                    className={`absolute inset-x-0 top-0 bottom-0 mx-auto w-px ${
                      risesFor(tool) ? 'bg-up' : 'bg-down'
                    } opacity-70`}
                  />
                  <span
                    className={`absolute inset-x-0 top-[3px] h-[5px] ${
                      risesFor(tool) ? 'bg-up' : 'bg-down'
                    }`}
                  />
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>

      {/* The names still reach a screen reader, and a search of the page. */}
      <ul className="sr-only">
        {MCP.groups.map((group) => (
          <li key={group.label}>
            {group.label}: {group.tools.join(', ')}
          </li>
        ))}
      </ul>
    </FigureFrame>
  );
}
