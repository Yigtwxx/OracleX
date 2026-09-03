'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import Modal from '@/components/ui/Modal';
import { useStore } from '@/store/useStore';
import { getAlarmSource } from '@/lib/alarms/registry';
import AlarmBuilder from './AlarmBuilder';
import AlarmEmailSettings from './AlarmEmailSettings';
import AlarmHistory from './AlarmHistory';
import AlarmList from './AlarmList';
import AlarmSourceRail, { type AlarmView } from './AlarmSourceRail';

const EMPTY_PARAMS: Record<string, string> = {};

/**
 * The alarm workspace.
 *
 * Two panes on a desktop — a catalogue of what can be watched on the left, the
 * builder or a list on the right — collapsing to one pane with a back button on
 * a phone. Mounted globally in ClientShell so a bell anywhere can open it.
 */
export default function AlarmCenter() {
  const isOpen = useStore((state) => state.isAlarmModalOpen);
  const draft = useStore((state) => state.alarmDraft);
  const closeAlarmModal = useStore((state) => state.closeAlarmModal);
  const alarmCount = useStore((state) => state.alarms.length);
  const historyCount = useStore((state) => state.alarmHistory.length);
  const emailConfirmed = useStore((state) => state.alarmEmail !== undefined);

  const [view, setView] = useState<AlarmView>({ kind: 'list' });
  const [query, setQuery] = useState('');
  // Which pane a phone is showing. Desktop shows both and ignores this.
  const [paneOnMobile, setPaneOnMobile] = useState<'rail' | 'detail'>('rail');

  // Opening with a draft lands straight on that source; opening cold lands on
  // whatever the user is more likely to want — their alarms if they have any.
  useEffect(() => {
    if (!isOpen) return;
    if (draft) {
      setView({ kind: 'source', sourceId: draft.sourceId });
      setPaneOnMobile('detail');
    } else {
      setView({ kind: 'list' });
      setPaneOnMobile('rail');
    }
    setQuery('');
  }, [isOpen, draft]);

  function select(next: AlarmView) {
    setView(next);
    setPaneOnMobile('detail');
  }

  const detailTitle =
    view.kind === 'source'
      ? getAlarmSource(view.sourceId).label
      : view.kind === 'list'
        ? 'My Alarms'
        : view.kind === 'email'
          ? 'Email Alerts'
          : 'History';

  return (
    <Modal
      isOpen={isOpen}
      onClose={closeAlarmModal}
      title="Alarm Center"
      fullScreen
      scrimClassName="scrim-blur"
    >
      <div className="flex h-full min-h-0">
        <aside
          className={`w-full sm:w-56 shrink-0 sm:border-r border-line ${
            paneOnMobile === 'rail' ? 'block' : 'hidden sm:block'
          }`}
        >
          <AlarmSourceRail
            view={view}
            onSelect={select}
            query={query}
            onQueryChange={setQuery}
            alarmCount={alarmCount}
            historyCount={historyCount}
            emailConfirmed={emailConfirmed}
          />
        </aside>

        <section
          className={`flex-1 min-w-0 min-h-0 ${
            paneOnMobile === 'detail' ? 'flex flex-col' : 'hidden sm:flex sm:flex-col'
          }`}
        >
          <div className="sm:hidden shrink-0 flex items-center gap-2 px-3 h-10 border-b border-line">
            <button
              type="button"
              onClick={() => setPaneOnMobile('rail')}
              className="flex items-center gap-1.5 text-base text-fg-muted hover:text-fg transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Sources
            </button>
            <span className="text-base text-fg-subtle truncate">· {detailTitle}</span>
          </div>

          <div className="flex-1 min-h-0">
            {view.kind === 'source' ? (
              <AlarmBuilder
                key={view.sourceId}
                sourceId={view.sourceId}
                initialParams={draft?.sourceId === view.sourceId ? draft.params : EMPTY_PARAMS}
                onCreated={() => select({ kind: 'list' })}
              />
            ) : view.kind === 'list' ? (
              <div className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar">
                <AlarmList />
              </div>
            ) : view.kind === 'email' ? (
              <AlarmEmailSettings />
            ) : (
              <AlarmHistory />
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}
