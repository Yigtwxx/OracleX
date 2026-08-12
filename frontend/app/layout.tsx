import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { AuthProvider } from '@/contexts/AuthContext';
import ClientShell from '@/components/ClientShell';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

// Prices, tickers and table figures render in mono so columns stay aligned.
const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Oracle-X | Financial Intelligence Terminal',
  description:
    'AI-powered financial analysis with blockchain verification. Real-time insights for stocks and crypto.',
  keywords: ['finance', 'AI', 'trading', 'stocks', 'crypto', 'blockchain', 'analysis'],
};

/**
 * Recovers from a chunk that never arrives.
 *
 * A cold start compiles chunks on demand, and when the machine is busy the
 * request can outlive webpack's load timeout. The layout chunk failing is the
 * worst case: React never hydrates, so the boot splash sits there server-
 * rendered and inert until the user presses F5 — which always works, because
 * the chunk has finished compiling by then. This does that reload for them.
 *
 * Deliberately an inline script rather than a component: anything that ships in
 * a chunk cannot rescue a failed chunk load, least of all the layout's own.
 */
const CHUNK_RECOVERY = `
(function () {
  var KEY = 'oracle-x:chunk-reload';
  // One reload per incident. A chunk that is genuinely gone (a stale build
  // after a deploy) would otherwise reload forever.
  var COOLDOWN_MS = 30000;
  // How long the page may stay server-rendered before it is presumed dead.
  // Long enough that a slow but working hydration is never interrupted.
  var HYDRATE_TIMEOUT_MS = 12000;

  function isChunkError(e) {
    if (!e) return false;
    if (e.name === 'ChunkLoadError') return true;
    return typeof e.message === 'string' && /Loading (CSS )?chunk .* failed/.test(e.message);
  }

  // A <script> or <link> that never arrives dispatches a bare Event at the
  // element itself — no .error, no .message, nothing isChunkError can read.
  // That is precisely the case this whole script exists for, and it was the
  // one case it did not cover.
  function isDeadAsset(target) {
    if (!target || target === window || !target.tagName) return false;
    if (target.tagName !== 'SCRIPT' && target.tagName !== 'LINK') return false;
    var url = target.src || target.href || '';
    return url.indexOf('/_next/') !== -1;
  }

  function recover() {
    try {
      var last = Number(sessionStorage.getItem(KEY) || 0);
      if (Date.now() - last < COOLDOWN_MS) return;
      sessionStorage.setItem(KEY, String(Date.now()));
    } catch (_) {
      // Private browsing can throw here. Reloading once unguarded still beats
      // leaving a dead page on screen.
    }
    location.reload();
  }

  // Capture phase: resource load failures do not bubble.
  window.addEventListener('error', function (event) {
    if (isChunkError(event.error) || isDeadAsset(event.target)) recover();
  }, true);

  window.addEventListener('unhandledrejection', function (event) {
    if (isChunkError(event.reason)) recover();
  });

  // The failure mode neither listener can see: a chunk request that hangs
  // rather than fails. Nothing errors, so the splash simply sits there
  // server-rendered and inert. ClientShell stamps data-hydrated the moment the
  // React tree is alive; if that has not happened by the deadline, it never
  // will without a reload.
  setTimeout(function () {
    if (!document.documentElement.hasAttribute('data-hydrated')) recover();
  }, HYDRATE_TIMEOUT_MS);
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: CHUNK_RECOVERY }} />
      </head>
      <body className="font-sans text-base antialiased">
        <AuthProvider>
          <ClientShell>{children}</ClientShell>
        </AuthProvider>
      </body>
    </html>
  );
}
