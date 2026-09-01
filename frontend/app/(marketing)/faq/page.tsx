import type { Metadata } from 'next';
import DocMasthead from '@/components/landing/DocMasthead';
import DocPage from '@/components/landing/DocPage';
import FaqList from '@/components/landing/FaqList';
import MarketingChrome from '@/components/landing/MarketingChrome';
import { FAQ_ENTRIES, FAQ_GROUPS } from '@/lib/marketing/faq';

export const metadata: Metadata = {
  title: 'Oracle-X | Questions',
  description:
    'What the terminal will and will not claim, where your data lives, and exactly how much of the market it covers.',
};

/** The spine's rows. Groups rather than questions — eighteen entries in a rail
 *  is a second page, not a navigation aid. */
const RAIL_ITEMS = FAQ_GROUPS.map((group, i) => ({
  id: group.id,
  index: String(i + 1).padStart(2, '0'),
  label: group.label,
}));

export default function FaqRoute() {
  return (
    <MarketingChrome>
      <DocPage
        sections={RAIL_ITEMS}
        masthead={
          <DocMasthead
            eyebrow="Questions"
            title="What it will not claim"
            dek="The uncomfortable answers are here too: the equity universe is small, the local model is the constraint, and a hosted provider means your prompts leave the machine."
            stat={`${FAQ_ENTRIES.length} questions · ${FAQ_GROUPS.length} groups`}
          />
        }
      >
        <div className="pt-6">
          <FaqList groups={FAQ_GROUPS} />
        </div>
      </DocPage>
    </MarketingChrome>
  );
}
