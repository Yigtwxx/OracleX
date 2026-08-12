'use client';

import { useState, useEffect } from 'react';
import { MessageSquare, Plus, Trash2, MessageCircle } from 'lucide-react';
import { isToday, isYesterday, parseISO } from 'date-fns';

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ChatSidebarProps {
  sessions: ChatSession[];
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
}

export default function ChatSidebar({
  sessions,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  isOpen,
  setIsOpen,
}: ChatSidebarProps) {
  const [groupedSessions, setGroupedSessions] = useState<{ [key: string]: ChatSession[] }>({});

  useEffect(() => {
    const groups: { [key: string]: ChatSession[] } = {
      Today: [],
      Yesterday: [],
      'Last 7 Days': [],
    };

    sessions.forEach((session) => {
      const date = parseISO(session.updated_at);
      if (isToday(date)) {
        groups['Today'].push(session);
      } else if (isYesterday(date)) {
        groups['Yesterday'].push(session);
      } else {
        groups['Last 7 Days'].push(session);
      }
    });

    setGroupedSessions(groups);
  }, [sessions]);

  return (
    <>
      {/* Mobile Overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setIsOpen(false)}
        />
      )}

      {/* Sidebar Container */}
      <div
        className={`fixed md:static inset-y-0 left-0 z-50 w-64 bg-surface border-r border-line transform transition-transform duration-200 ease-out flex flex-col ${
          isOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
      >
        {/* Header / New Chat */}
        <div className="shrink-0 p-3 border-b border-line">
          <button
            onClick={onNewChat}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md bg-surface-2 border border-line hover:border-line-strong transition-colors"
          >
            <Plus className="w-3.5 h-3.5 text-fg-muted" />
            <span className="text-base text-fg">New Chat</span>
          </button>
        </div>

        {/* Session List */}
        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-3 space-y-4">
          {Object.entries(groupedSessions).map(
            ([group, groupSessions]) =>
              groupSessions.length > 0 && (
                <div key={group}>
                  <h3 className="label mb-2 px-1">{group}</h3>
                  <div className="space-y-0.5">
                    {groupSessions.map((session) => (
                      <div
                        key={session.id}
                        role="button"
                        tabIndex={0}
                        className={`group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors ${
                          currentSessionId === session.id
                            ? 'bg-surface-2 text-fg'
                            : 'text-fg-muted hover:text-fg hover:bg-surface-2'
                        }`}
                        onClick={() => {
                          onSelectSession(session.id);
                          if (window.innerWidth < 768) setIsOpen(false);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSelectSession(session.id);
                          }
                        }}
                      >
                        <MessageSquare className="w-3 h-3 shrink-0" />
                        <span className="flex-1 text-base truncate">{session.title}</span>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSession(session.id);
                          }}
                          aria-label={`Delete chat ${session.title}`}
                          className={`shrink-0 p-0.5 rounded text-fg-subtle hover:text-down transition-opacity opacity-0 group-hover:opacity-100 focus-visible:opacity-100 ${
                            currentSessionId === session.id ? 'opacity-100' : ''
                          }`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )
          )}

          {sessions.length === 0 && (
            <div className="text-center py-10 px-4">
              <MessageCircle className="w-5 h-5 text-fg-subtle mx-auto mb-2" />
              <p className="text-base text-fg-muted">No chat history yet.</p>
              <p className="text-xs text-fg-subtle mt-1">Chats are stored for 7 days.</p>
            </div>
          )}
        </div>

        <div className="shrink-0 p-3 border-t border-line">
          <p className="text-xs text-center text-fg-subtle">Oracle AI &copy; 2026</p>
        </div>
      </div>
    </>
  );
}
