'use client';

import { useState, useRef, useEffect, ReactNode } from 'react';
import {
  Brain,
  Send,
  Loader2,
  Square,
  Sparkles,
  Microscope,
  Clock,
  Zap,
  TrendingUp,
  Bitcoin,
  HelpCircle,
  Menu,
  Trash2,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';
import ChatSidebar from './ChatSidebar';
import ChatModeBackdrop from './ChatModeBackdrop';
import ThinkingCandles from './ThinkingCandles';
import { useOptionalAuth } from '@/contexts/AuthContext';
import {
  fetchChatSessions,
  createChatSession,
  deleteChatSession,
  fetchSessionMessages,
  saveChatMessage as saveChatMessageApi,
  startChatJob,
  cancelChatJob,
  fetchChatStatus,
  type ChatSession,
} from '@/lib/api';
import { useChatJob } from '@/hooks/queries';
import StepTimeline from './chat/StepTimeline';
import Markdown from './ui/Markdown';
import { toStepRow, toStoredSteps, type ChatStep, type Citation } from '@/lib/chat-job';

type ResponseStyle = 'concise' | 'detailed';

// How much of the transcript travels with a turn. See the comment where it is
// used — the lower bound is set by `chat_focus.FOCUS_LOOKBACK_TURNS` on the
// server, which is 4 user messages.
const HISTORY_WINDOW = 12;
const HISTORY_MESSAGE_CHARS = 2000;

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinkingTime?: number;
  timestamp: Date;
  /**
   * The mode this message was exchanged under, frozen at creation so the
   * entrance animation cannot be replayed by later mode switches. Undefined for
   * messages restored from history: the backend does not persist the mode, and
   * animating a bubble that has been on screen since page load would be a lie.
   */
  mode?: ResponseStyle;
  /**
   * What the turn actually did to produce this answer. Undefined for restored
   * messages for the same reason `mode` is — the steps are not persisted yet.
   */
  steps?: ChatStep[];
  /**
   * The pages behind the answer. Not persisted either, so a restored message
   * shows the links the model chose to inline and nothing more.
   */
  citations?: Citation[];
  /** The asset this turn resolved to, and whether it was carried over. */
  focusSymbol?: string;
  focusInherited?: boolean;
}

// The style picker used to be two words that swapped a grey background, so the
// only way to know which Oracle you were talking to was to remember. It is a
// mode, not a preference: it decides whether the model runs a reasoning pass and
// whether it answers in 120 or 450 words. Each mode therefore owns a colour, and
// every control the mode governs — the pill, the composer, the send button, the
// pending bubble, the header chip — repeats it, so the state is readable from
// anywhere on the screen rather than only from the pill that set it.
//
// The class strings are written out rather than composed, because Tailwind only
// generates classes it can read as literals in the source: `bg-mode-${style}`
// compiles to nothing at all, silently.
const RESPONSE_STYLES = {
  concise: {
    label: 'Concise',
    icon: Zap,
    blurb: 'Short answer — under ~120 words: the call, the figures, the one risk.',
    placeholder: 'Ask Oracle a quick question…',
    pendingTitle: 'Oracle is answering…',
    pendingNote: 'A concise reply lands in a few seconds',
    chip: 'bg-mode-concise-bg text-mode-concise border-mode-concise',
    tint: 'text-mode-concise',
    composer: 'focus-within:border-mode-concise',
    // The deep stop, not the label stop: a filled button is read at a glance and
    // the lifted hue would take white down to 3.7:1.
    send: 'bg-mode-concise-solid text-white',
    enter: 'msg-in-concise',
    pending: 'pending-concise',
  },
  detailed: {
    label: 'Detailed',
    icon: Microscope,
    blurb: 'Full analysis — 300-450 words with a reasoning pass. May take a minute.',
    placeholder: 'Ask Oracle for a full analysis…',
    pendingTitle: 'Oracle is thinking…',
    pendingNote: 'Detailed analysis takes time',
    chip: 'bg-mode-detailed-bg text-mode-detailed border-mode-detailed',
    tint: 'text-mode-detailed',
    composer: 'focus-within:border-mode-detailed',
    send: 'bg-mode-detailed-solid text-white',
    enter: 'msg-in-detailed',
    pending: 'pending-detailed',
  },
} as const;

const STYLE_ORDER = ['concise', 'detailed'] as const;

// Suggested prompts for quick start
const SUGGESTED_PROMPTS = [
  { icon: Bitcoin, text: 'Analyze Bitcoin technically' },
  { icon: TrendingUp, text: 'What do you think about NVDA?' },
  { icon: Zap, text: 'How is the market today?' },
  { icon: HelpCircle, text: 'Best DeFi coins to buy?' },
];

/**
 * What the turn did, folded away above the answer.
 *
 * Collapsed by default and on purpose: the steps matter most while they are
 * happening, and four permanently expanded rows above every reply would bury
 * the thing the user actually asked for. Failures are surfaced in the summary
 * line so a turn that lost a source does not look identical to one that did not.
 */
function StepSummary({ steps }: { steps: ChatStep[] }) {
  const [open, setOpen] = useState(false);
  const failed = steps.filter((s) => s.status === 'failed' || s.status === 'skipped').length;
  const total = steps.reduce((sum, s) => sum + (s.durationSeconds ?? 0), 0);

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-xs text-fg-subtle hover:text-fg-muted transition-colors"
      >
        <ChevronRight
          className={`w-3 h-3 transition-transform ${open ? 'rotate-90' : ''}`}
          aria-hidden
        />
        <span>
          {steps.length} step{steps.length === 1 ? '' : 's'} · {total.toFixed(0)}s
          {failed > 0 && <span className="text-down"> · {failed} incomplete</span>}
        </span>
      </button>
      {open && (
        <div className="mt-2">
          <StepTimeline steps={steps} dense />
        </div>
      )}
    </div>
  );
}

export default function OracleChatPage() {
  const { user } = useOptionalAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isAvailable, setIsAvailable] = useState<boolean | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [responseStyle, setResponseStyle] = useState<ResponseStyle>('detailed');
  // The style the in-flight request was sent with. Switching modes while Oracle
  // is answering must not recolour the pending bubble to describe a request that
  // was never made.
  const [pendingStyle, setPendingStyle] = useState<ResponseStyle>('detailed');

  // The turn in flight. The answer no longer comes back from the call that
  // started it: the backend runs the turn as a job so its steps can be reported
  // while they happen, and this id is what the poller follows.
  const [activeJobId, setActiveJobId] = useState<string | undefined>(undefined);
  const [followups, setFollowups] = useState<string[]>([]);
  const chatJob = useChatJob(activeJobId);

  // Session State
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Which job the answer has already been collected for, and which session the
  // in-flight turn belongs to — the user can switch sessions while waiting.
  const handledJobRef = useRef<string | undefined>(undefined);
  const jobSessionRef = useRef<string | null>(null);
  // A session this component just created for the turn it is sending. Its
  // messages are already on screen, and the row that persists them is still in
  // flight, so loading its history would replace the optimistic bubble with an
  // empty list — the first message of a new chat would vanish.
  const freshSessionRef = useRef<string | null>(null);

  // Check chat availability on mount
  useEffect(() => {
    checkAvailability();
  }, []);

  // Load chat sessions when user is available
  useEffect(() => {
    if (user?.id) {
      loadSessions();
    }
  }, [user?.id]);

  // Load messages when session changes
  useEffect(() => {
    if (currentSessionId && freshSessionRef.current === currentSessionId) {
      freshSessionRef.current = null;
      return;
    }
    if (user?.id && currentSessionId) {
      loadSessionMessages(currentSessionId);
    } else if (!currentSessionId) {
      setMessages([]);
    }
  }, [currentSessionId, user?.id]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const checkAvailability = async () => {
    try {
      const { available } = await fetchChatStatus();
      setIsAvailable(available);
    } catch {
      setIsAvailable(false);
    }
  };

  const loadSessions = async () => {
    if (!user?.id) return;
    try {
      setSessions(await fetchChatSessions());
    } catch (error) {
      console.error('Failed to load sessions:', error);
    }
  };

  const loadSessionMessages = async (sessionId: string) => {
    setIsLoadingHistory(true);
    try {
      const history = await fetchSessionMessages(sessionId);
      setMessages(
        history.map((m) => ({
          role: m.role,
          content: m.content,
          thinkingTime: m.thinking_time,
          timestamp: new Date(m.created_at),
          // Null for user messages and for turns that predate the timeline —
          // both render as no summary rather than as an empty one.
          steps: toStoredSteps(m.steps),
        }))
      );
    } catch (error) {
      console.error('Failed to load session messages:', error);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleNewChat = () => {
    setCurrentSessionId(null);
    setMessages([]);
    setIsSidebarOpen(false); // Mobile UX
  };

  const handleDeleteSession = async (sessionId: string) => {
    if (!user?.id) return;
    try {
      await deleteChatSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (currentSessionId === sessionId) {
        handleNewChat();
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  };

  const saveChatMessage = async (
    role: 'user' | 'assistant',
    content: string,
    sessionId?: string,
    thinkingTime?: number,
    steps?: ChatStep[]
  ) => {
    if (!user?.id) return;

    try {
      await saveChatMessageApi({
        role,
        content,
        session_id: sessionId,
        thinking_time: thinkingTime,
        steps: steps?.map(toStepRow),
      });
    } catch (error) {
      console.error('Failed to save chat message:', error);
    }
  };

  /**
   * Collect a finished turn.
   *
   * Guarded by a ref rather than by the effect's dependency list: React may run
   * an effect more than once for the same state, and without the guard a
   * re-render would append the same answer twice.
   */
  useEffect(() => {
    const job = chatJob.data;
    if (!job || !activeJobId) return;
    if (job.status !== 'done' && job.status !== 'error') return;
    if (handledJobRef.current === activeJobId) return;
    handledJobRef.current = activeJobId;

    const sessionId = jobSessionRef.current;
    const result = job.result;

    if (job.status === 'error' || !result) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `**Something went wrong**\n\n${job.error ?? 'The turn did not finish.'}`,
          timestamp: new Date(),
          mode: pendingStyle,
          steps: job.steps,
        },
      ]);
    } else {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: result.response,
          thinkingTime: result.thinkingTime,
          timestamp: new Date(),
          mode: pendingStyle,
          steps: job.steps,
          citations: result.citations,
          focusSymbol: result.detectedSymbol,
          focusInherited: result.focusInherited,
        },
      ]);

      // Suggestions are per-turn, not per-message: they belong to the answer on
      // screen, and keeping them on an older bubble would offer the user
      // follow-ups to a conversation that has already moved on.
      setFollowups(result.followups ?? []);

      // The backend auto-titles a session on its first turn and returns the
      // title it persisted, so the sidebar can drop the raw message slice it
      // was created with without refetching the session list.
      const newTitle = result.sessionTitle;
      if (newTitle && sessionId) {
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s))
        );
      }

      void saveChatMessage(
        'assistant',
        result.response,
        sessionId || undefined,
        result.thinkingTime,
        job.steps
      );
    }

    setActiveJobId(undefined);
    setIsLoading(false);
    inputRef.current?.focus();
    // `pendingStyle` is frozen for the duration of the turn and must not
    // re-trigger collection if the user flips the mode while waiting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatJob.data, activeJobId]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;

    const userMessage: ChatMessage = {
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
      mode: responseStyle,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setFollowups([]);
    setPendingStyle(responseStyle);
    setIsLoading(true);

    // Initialize session if needed
    let activeSessionId = currentSessionId;
    if (!activeSessionId && user?.id) {
      try {
        // Generate title from first message
        const title = text.trim().slice(0, 30) + (text.length > 30 ? '...' : '');
        const session = await createChatSession(title);
        if (session?.id) {
          activeSessionId = session.id;
          freshSessionRef.current = session.id;
          setCurrentSessionId(session.id);
          setSessions((prev) => [session, ...prev]);
        }
      } catch (e) {
        console.error('Failed to create session', e);
      }
    }

    // Save user message to DB
    await saveChatMessage('user', text.trim(), activeSessionId || undefined);

    // OPTIMISTIC UPDATE: Move current session to top
    if (activeSessionId) {
      setSessions((prev) => {
        const sessionIndex = prev.findIndex((s) => s.id === activeSessionId);
        if (sessionIndex > -1) {
          const updatedSession = {
            ...prev[sessionIndex],
            updated_at: new Date().toISOString(),
          };
          const newSessions = [...prev];
          newSessions.splice(sessionIndex, 1);
          return [updatedSession, ...newSessions];
        }
        return prev;
      });
    }

    try {
      // The transcript the turn resolves its subject from, bounded.
      //
      // This used to send every message of the session on every turn, with no
      // cap on count or length — a long conversation grew the request until the
      // server's own trimming was the only thing keeping the prompt in budget.
      //
      // The floor is not arbitrary: `chat_focus.FOCUS_LOOKBACK_TURNS` walks
      // back four *user* messages looking for the subject of a follow-up, so
      // this window has to comfortably contain that. Cut it below eight and
      // sticky focus quietly stops working on a restored session.
      const history = messages.slice(-HISTORY_WINDOW).map((m) => ({
        role: m.role,
        content: m.content.slice(0, HISTORY_MESSAGE_CHARS),
      }));

      // Start the turn as a job and hand it to the poller. The answer arrives
      // in the effect below, so this function's work ends here — `isLoading`
      // stays true until the job settles.
      const job = await startChatJob({
        message: text.trim(),
        history: history.length > 0 ? history : undefined,
        session_id: activeSessionId ?? undefined,
        style: responseStyle,
      });
      jobSessionRef.current = activeSessionId ?? null;
      setActiveJobId(job.jobId);
    } catch (error) {
      const errorMessage: ChatMessage = {
        role: 'assistant',
        content: '**Connection error**\n\nOracle is unreachable. Please try again in a moment.',
        timestamp: new Date(),
        mode: responseStyle,
      };
      setMessages((prev) => [...prev, errorMessage]);
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(inputValue);
  };

  /**
   * Stop the turn that is running.
   *
   * Clearing `activeJobId` is what actually stops this client: it disables the
   * poll and takes the collection effect below out of play, so the answer this
   * turn was about to produce is never appended. That is also why there is no
   * "cancelled" branch down there — with no active job id, the effect returns
   * before it can render anything.
   *
   * The local state goes first and the request after, because the point of
   * pressing stop is that the composer comes back immediately. The server call
   * still matters: it frees the LLM and the upstream feeds rather than leaving
   * them working on an answer nobody will read.
   */
  const cancelTurn = () => {
    const jobId = activeJobId;
    if (!jobId) return;

    setActiveJobId(undefined);
    setIsLoading(false);
    inputRef.current?.focus();

    void cancelChatJob(jobId).catch(() => {
      // The turn is already gone from this client's point of view. A failed
      // cancel means the server keeps working for a few more seconds and then
      // throws the answer away — worth nothing to report.
    });
  };

  const handleSuggestionClick = (text: string) => {
    sendMessage(text);
  };

  const mode = RESPONSE_STYLES[responseStyle];
  const pendingMode = RESPONSE_STYLES[pendingStyle];

  return (
    // Opaque on purpose: this is the one page that carries its own backdrop,
    // and the global one in globals.css › APP BACKDROP would sit under it in a
    // shape that matches neither the column nor the mask, reading as a box.
    <div className="h-full flex bg-bg overflow-hidden">
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={setCurrentSessionId}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        isOpen={isSidebarOpen}
        setIsOpen={setIsSidebarOpen}
      />

      {/* Main Chat Area */}
      <div className="relative isolate flex-1 flex flex-col h-full min-w-0">
        {/* The mode's own depth, behind everything. It only shows through the
            message area — the header and composer are opaque surfaces — which is
            exactly the region that had no mode signal in it. */}
        <ChatModeBackdrop mode={responseStyle} busy={isLoading} />

        {/* Header */}
        <div className="relative z-10 h-10 px-4 border-b border-line flex items-center gap-2.5 bg-surface shrink-0">
          <button
            onClick={() => setIsSidebarOpen(true)}
            aria-label="Open chat history"
            className="md:hidden p-1 -ml-1 text-fg-muted hover:text-fg"
          >
            <Menu className="w-4 h-4" />
          </button>

          <Brain className="w-3.5 h-3.5 text-fg-muted shrink-0" />
          <h2 className="text-base font-semibold text-fg">Oracle Chat</h2>
          <p className="text-xs text-fg-subtle hidden md:block">
            Crypto, stock and market analysis assistant
          </p>

          <div className="ml-auto flex items-center gap-3">
            {/* Repeated here because the picker sits at the bottom of a
                scrolling column: mid-conversation it is the only place the
                active mode is still visible. */}
            <span
              className={`flex items-center gap-1.5 text-xs px-1.5 py-0.5 rounded-md border ${mode.chip}`}
            >
              <mode.icon className="w-3 h-3" />
              <span className="hidden sm:inline">{mode.label}</span>
            </span>

            {isAvailable === true && (
              <span className="flex items-center gap-1.5 text-xs ws-connected">
                <span className="w-1.5 h-1.5 rounded-full bg-up live-indicator" />
                <span className="hidden md:inline">Online</span>
              </span>
            )}
            {isAvailable === false && (
              <span className="flex items-center gap-1.5 text-xs ws-disconnected">
                <span className="w-1.5 h-1.5 rounded-full bg-down" />
                <span className="hidden md:inline">Offline</span>
              </span>
            )}
          </div>
        </div>

        {/* Messages Area */}
        <div className="relative z-10 flex-1 min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-3">
          {messages.length === 0 ? (
            // Welcome State
            <div className="h-full flex flex-col items-center justify-center text-center px-6">
              <Brain className="w-7 h-7 text-fg-subtle mb-4" />
              <h3 className="text-lg font-semibold text-fg mb-2">Welcome to Oracle</h3>
              <p className="text-base text-fg-muted max-w-md mb-6">
                Ask questions about cryptocurrencies, stocks and market analysis. Oracle takes time
                to provide detailed and accurate answers.
              </p>

              {/* Suggested Prompts */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-lg w-full">
                {SUGGESTED_PROMPTS.map((prompt, index) => (
                  <button
                    key={index}
                    onClick={() => handleSuggestionClick(prompt.text)}
                    className="flex items-center gap-2.5 p-3 rounded-lg bg-surface border border-line hover:border-line-strong transition-colors text-left"
                  >
                    <prompt.icon className="w-3.5 h-3.5 text-fg-subtle shrink-0" />
                    <span className="text-base text-fg-muted">{prompt.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            // Chat Messages
            <>
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} ${
                    message.mode ? RESPONSE_STYLES[message.mode].enter : ''
                  }`}
                >
                  {/* 12px rather than the 8px the rest of the terminal uses: a
                      message is the one surface here that is a piece of speech
                      rather than a panel, and it is allowed to look like it. */}
                  <div
                    className={`max-w-[80%] rounded-xl p-3 ${
                      message.role === 'user'
                        ? 'bg-accent text-white'
                        : 'bg-surface border border-line'
                    }`}
                  >
                    {message.role === 'assistant' && (
                      <div className="mb-2 pb-2 border-b border-line">
                        <div className="flex items-center gap-2">
                          <span className="label">Oracle</span>
                          {message.thinkingTime && (
                            <span className="flex items-center gap-1 text-xs font-mono tabnum text-fg-subtle ml-auto">
                              <Clock className="w-2.5 h-2.5" />
                              {message.thinkingTime}s
                            </span>
                          )}
                        </div>
                        {message.steps && message.steps.length > 0 && (
                          <StepSummary steps={message.steps} />
                        )}
                      </div>
                    )}
                    {/* The shared renderer, not an inline one. The chat page
                        used to define its own `ReactMarkdown` components with
                        no `remarkGfm`, which meant the tables `chat/system.md`
                        explicitly asks the model for arrived as rows of raw
                        pipe characters. The `prose prose-*` classes went with
                        it — Tailwind Typography is not installed. */}
                    {message.role === 'assistant' ? (
                      <Markdown content={message.content} variant="chat" />
                    ) : (
                      <p className="text-base text-fg">{message.content}</p>
                    )}

                    {message.role === 'assistant' && message.focusSymbol && (
                      <div className="mt-2.5 flex items-center gap-1.5">
                        <span className="label">Read</span>
                        <span className="px-1.5 py-0.5 rounded-md bg-surface-2 border border-line text-xs font-mono tabnum text-fg">
                          {message.focusSymbol}
                        </span>
                        {/* Said out loud on purpose. The turn answered about an
                            asset this message never named, and a reader who
                            cannot see that has no way to catch the one case
                            where the carry-over was wrong. */}
                        {message.focusInherited && (
                          <span className="text-xs text-fg-subtle">carried from earlier</span>
                        )}
                      </div>
                    )}

                    {message.citations && message.citations.length > 0 && (
                      <div className="mt-3 pt-2.5 border-t border-line">
                        <p className="label mb-1.5">Sources</p>
                        <ul className="flex flex-wrap gap-x-3 gap-y-1">
                          {message.citations.map((citation) => (
                            <li key={citation.url}>
                              <a
                                href={citation.url}
                                target="_blank"
                                rel="noopener noreferrer nofollow"
                                className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                              >
                                {citation.label}
                                <ExternalLink className="w-3 h-3" aria-hidden="true" />
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {/* Where the conversation could go next.
                  Shown only under the latest answer and only while nothing is
                  in flight: a suggestion is about the turn on screen, and
                  leaving one attached to an older bubble would offer a
                  follow-up to a conversation that has already moved on. */}
              {!isLoading && followups.length > 0 && (
                <div className="flex justify-start">
                  <div className="flex flex-wrap gap-1.5 max-w-[80%] pl-1">
                    {followups.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        onClick={() => handleSuggestionClick(suggestion)}
                        className="px-2.5 py-1 rounded-md border border-line bg-surface text-xs text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Loading indicator */}
              {isLoading && (
                <div className={`flex justify-start ${pendingMode.enter}`}>
                  {/* No card around the pending turn: the step list reads as a
                      thread growing downward, and a box drawn around a list that
                      changes height every second only frames the movement. */}
                  <div
                    className={`relative overflow-hidden rounded-xl py-2 pl-1 pr-3 max-w-[80%] ${pendingMode.pending}`}
                  >
                    <div className="relative z-10 flex items-center gap-2.5">
                      {/* A spinner would only say "something is happening".
                          The candles say what: the tape is being read. */}
                      <ThinkingCandles />
                      <div>
                        <p className="text-base text-fg">{pendingMode.pendingTitle}</p>
                        <p className="text-xs text-fg-subtle">{pendingMode.pendingNote}</p>
                      </div>
                    </div>

                    {/* The steps as they happen. Absent for the first second or
                        so while the job spins up, which is why the candles and
                        the copy above stay — with no steps yet this bubble looks
                        exactly as it always did. */}
                    {(chatJob.data?.steps?.length ?? 0) > 0 && (
                      <div className="relative z-10 mt-2.5 pl-1">
                        <StepTimeline steps={chatJob.data!.steps} dense />
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input Area */}
        <div className="relative z-10 shrink-0 p-3 border-t border-line bg-surface">
          <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
            {/* Style Selector */}
            <div
              className="flex justify-center mb-2 gap-1"
              role="group"
              aria-label="Response style"
            >
              {STYLE_ORDER.map((style) => {
                const option = RESPONSE_STYLES[style];
                const isActive = responseStyle === style;
                return (
                  <button
                    key={style}
                    type="button"
                    aria-pressed={isActive}
                    onClick={() => setResponseStyle(style)}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-sm border transition-colors ${
                      isActive
                        ? option.chip
                        : 'border-transparent text-fg-muted hover:text-fg hover:bg-surface-2'
                    }`}
                  >
                    <option.icon className="w-3 h-3" />
                    {option.label}
                  </button>
                );
              })}
            </div>

            <div
              className={`flex items-center gap-2 p-1.5 rounded-lg bg-surface-2 border border-line transition-colors ${mode.composer}`}
            >
              <mode.icon className={`w-3.5 h-3.5 ml-1.5 ${mode.tint}`} />
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={mode.placeholder}
                className="flex-1 bg-transparent text-base text-fg placeholder:text-fg-subtle outline-none py-1"
                disabled={isLoading || isAvailable === false}
              />
              <button
                /* While a turn is running this is a stop button, not a
                   disabled send button. A turn can spend minutes gathering
                   evidence, and the spinner used to be the one thing on screen
                   that looked like a control and was not — so a question asked
                   by mistake had to be waited out. */
                type={isLoading ? 'button' : 'submit'}
                aria-label={isLoading ? 'Stop this turn' : 'Send message'}
                onClick={isLoading ? cancelTurn : undefined}
                disabled={isLoading ? false : !inputValue.trim() || isAvailable === false}
                className={`group flex items-center justify-center w-8 h-8 rounded-md disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-opacity ${mode.send}`}
              >
                {isLoading ? (
                  <>
                    {/* Spinning until the pointer is over it, then a stop
                        square: one says the turn is working, the other says
                        what pressing will do. */}
                    <Loader2 className="w-3.5 h-3.5 animate-spin group-hover:hidden" />
                    <Square className="w-3 h-3 hidden group-hover:block fill-current" />
                  </>
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
            {/* States what the selected mode actually changes — length and
                whether there is a reasoning pass — rather than the old line,
                which described detailed mode whichever one was selected. */}
            <p className="text-center text-xs text-fg-subtle mt-2">{mode.blurb}</p>
          </form>
        </div>
      </div>
    </div>
  );
}
