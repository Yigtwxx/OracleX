import ClientShell from '@/components/ClientShell';

/**
 * The terminal shell: navigation, ticker, boot gate, toasts. Every route except
 * the marketing landing page lives under this group, which is what lets `/`
 * render as a plain scrolling document with none of it.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <ClientShell>{children}</ClientShell>;
}
