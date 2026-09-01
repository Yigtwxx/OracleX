import type { Metadata } from 'next';
import DocMasthead from '@/components/landing/DocMasthead';
import DocPage from '@/components/landing/DocPage';
import DocSectionBlock from '@/components/landing/DocSectionBlock';
import ChainDiagram from '@/components/landing/figures/ChainDiagram';
import HealthFigure from '@/components/landing/figures/HealthFigure';
import SkillsFigure from '@/components/landing/figures/SkillsFigure';
import SurfaceFigure from '@/components/landing/figures/SurfaceFigure';
import TestsFigure from '@/components/landing/figures/TestsFigure';
import ToolsFigure from '@/components/landing/figures/ToolsFigure';
import MarketingChrome from '@/components/landing/MarketingChrome';
import { API, MCP, TESTS, VERSION } from '@/lib/generated/repo-facts';
import { DEVELOPER_SECTIONS } from '@/lib/marketing/sections';

export const metadata: Metadata = {
  title: 'Oracle-X | Build against it',
  description:
    'The HTTP surface, the MCP tools, the agent skills and the provider chain — with every number on the page generated from the source it describes.',
};

/**
 * The failure taxonomy, shown rather than described.
 *
 * The one section with a code block instead of a figure: the claim is about the
 * shape of a return value, and a diagram of three boxes would be a longer way of
 * writing the same three lines.
 */
const FAILURE_SAMPLE = `# unreachable — nothing is listening
{ "ok": false, "reason": "no instance at http://localhost:8000" }

# declined — the instance answered, and said no
{ "ok": false, "reason": "no price could be resolved for FOO" }

# answered
{ "symbol": "BTCUSDT", "price": 56912.4, "as_of": "..." }`;

/** Which figure hangs beside which section. Keyed by id so a reordered page
 *  cannot silently pair the wrong two. */
const FIGURES: Record<string, React.ReactNode> = {
  surface: <SurfaceFigure />,
  tools: <ToolsFigure />,
  skills: <SkillsFigure />,
  models: <ChainDiagram />,
  health: <HealthFigure />,
  checks: <TestsFigure />,
};

export default function DevelopersRoute() {
  return (
    <MarketingChrome>
      <DocPage
        sections={DEVELOPER_SECTIONS}
        masthead={
          <DocMasthead
            eyebrow="Developers"
            title="Build against it"
            dek="Everything the terminal renders, it fetched over HTTP — and everything below is generated from the code it describes, so a number that stops being true fails the build instead of quietly ageing."
            stat={`${VERSION} · ${API.operations} operations · ${MCP.total} tools · ${TESTS.total} tests`}
          />
        }
      >
        {DEVELOPER_SECTIONS.map((section) => (
          <DocSectionBlock key={section.id} section={section} figure={FIGURES[section.id]}>
            {section.id === 'failure' && (
              <pre className="custom-scrollbar mt-5 overflow-x-auto rounded-md border border-line bg-surface-2 p-3 font-mono text-2xs leading-relaxed text-fg-muted">
                <code>{FAILURE_SAMPLE}</code>
              </pre>
            )}
          </DocSectionBlock>
        ))}
      </DocPage>
    </MarketingChrome>
  );
}
