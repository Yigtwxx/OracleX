import type { Metadata } from 'next';
import DocMasthead from '@/components/landing/DocMasthead';
import DocPage from '@/components/landing/DocPage';
import DocSectionBlock from '@/components/landing/DocSectionBlock';
import MarketingChrome from '@/components/landing/MarketingChrome';
import TrackRecordBoard from '@/components/track-record/TrackRecordBoard';
import { TRACK_RECORD_SECTIONS } from '@/lib/marketing/track-record';

export const metadata: Metadata = {
  title: 'Oracle-X | Track record',
  description:
    'Every directional call the terminal has made, scored against what the price actually did — with the best fixed answer printed beside it, and the sample size where a rate would be noise.',
};

/**
 * The accuracy page.
 *
 * Public and unauthenticated on purpose: a record of the terminal's own hit
 * rate that only its operator could read would be a private note. It is the one
 * marketing page whose figures are live rather than generated at build time,
 * which is why the board is a client island — the prose stays on the server so
 * this file can still export `metadata`, and the board renders its own notice
 * when no instance answers rather than filling the table with zeros.
 */
export default function TrackRecordRoute() {
  return (
    <MarketingChrome>
      <DocPage
        sections={TRACK_RECORD_SECTIONS}
        masthead={
          <DocMasthead
            eyebrow="Track record"
            title="Scored, not asserted"
            dek="A terminal that publishes directional calls and never checks them is asking to be believed on its tone. These are the calls, measured against what the price did next — including the ones that were wrong, the ones too thin to score, and the ones nothing could price at all."
          />
        }
      >
        {TRACK_RECORD_SECTIONS.map((section) => (
          <DocSectionBlock key={section.id} section={section}>
            {section.id === 'record' && <TrackRecordBoard />}
          </DocSectionBlock>
        ))}
      </DocPage>
    </MarketingChrome>
  );
}
